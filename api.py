from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy
from logger import get_logger
from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL
from pydantic import BaseModel, field_validator
import re
import requests
import json

log = get_logger("API")

app = FastAPI(title="PolySINT Core Engine")
analyst = PolyAnalyst()

# Pre-filter: only consider markets above this volume before hitting CLOB.
MIN_VOLUME_FOR_CLOB = 5000

# Max concurrent CLOB requests
CLOB_WORKERS = 20

# How long (in seconds) a cached analysis is considered fresh before the next
# request triggers a new LLM call. 3600 = 1 hour.
ANALYSIS_CACHE_TTL = 3600

# ─── Input limits ─────────────────────────────────────────────────────────────
# Prevents oversized strings reaching SQLite LIKE or the LLM prompt
MAX_SEARCH_LEN = 200
MAX_LABEL_LEN = 80
# Ethereum addresses are always exactly 42 characters (0x + 40 hex chars)
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
# Market IDs from Polymarket are numeric strings — reject anything else
MARKET_ID_RE = re.compile(r'^[0-9]+$')

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")

def _validate_address(address: str) -> str:
    """Raises 400 if address is not a valid 42-char 0x Ethereum address."""
    if not ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=400,
            detail="Invalid address. Must be a 42-character 0x Ethereum address."
        )
    return address

def _enrich_market(m: dict) -> dict | None:
    """
    Fetches CLOB history for a single market and attaches shift + current_price.
    Returns None if the market should be excluded (settled or no data).
    """
    clob_token_id = m.get("clob_token_id")
    m['shift'] = 0.0
    m['current_price'] = None

    if clob_token_id:
        history = get_price_history(clob_token_id)
        if history:
            m['current_price'] = float(history[-1]["p"])
            if len(history) >= 2:
                m['shift'] = round((float(history[-1]["p"]) - float(history[0]["p"])) * 100, 1)
    else:
        try:
            db = get_db()
            snap = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1",
                (m['id'],)
            ).fetchone()
            db.close()
            if snap:
                prices = json.loads(snap['prices'])
                if prices:
                    val = float(prices[0])
                    m['current_price'] = val
        except Exception:
            pass

    # Drop settled markets
    if m['current_price'] is not None:
        if m['current_price'] > 0.98 or m['current_price'] < 0.02:
            return None

    return m


@app.get("/markets")
def search_markets(
    limit: int = 50,
    search: str = None,
    vol_min: float = Query(default=None, ge=0, description="Minimum volume (inclusive)"),
    vol_max: float = Query(default=None, ge=0, description="Maximum volume (inclusive)"),
):
    # Reject oversized search strings before they reach SQLite
    if search is not None and len(search) > MAX_SEARCH_LEN:
        raise HTTPException(status_code=400, detail=f"Search query too long (max {MAX_SEARCH_LEN} chars).")

    db = get_db()
    try:
        query = "SELECT * FROM markets"
        params = []
        if search:
            query += " WHERE question LIKE ?"
            params.append(f"%{search}%")

        all_markets = [dict(r) for r in db.execute(query, params).fetchall()]
    finally:
        db.close()

    # Volume pre-filter: use MIN_VOLUME_FOR_CLOB as default floor when no search,
    # then apply any user-supplied bounds on top.
    volume_floor = MIN_VOLUME_FOR_CLOB if not search else 0

    candidates = []
    for m in all_markets:
        vol = m.get('volume') or 0
        if vol < volume_floor:
            continue
        if vol_min is not None and vol < vol_min:
            continue
        if vol_max is not None and vol > vol_max:
            continue
        candidates.append(m)

    enriched = []
    with ThreadPoolExecutor(max_workers=CLOB_WORKERS) as executor:
        futures = {executor.submit(_enrich_market, m): m for m in candidates}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    enriched.append(result)
            except Exception as e:
                log.error(f"Market enrichment failed: {e}")

    enriched.sort(key=lambda x: (abs(x.get('shift', 0.0)), x.get('volume') or 0.0), reverse=True)
    return enriched[:limit]


@app.get("/watchlist")
def get_watchlist():
    db = get_db()
    try:
        res = db.execute("SELECT * FROM watch_list ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in res]
    finally:
        db.close()

@app.get("/wallets/{address}/unmask")
def unmask_wallet(address: str):
    _validate_address(address)
    real_owner = unmask_proxy(address)
    return {"proxy": address, "real_owner": real_owner}


@app.get("/markets/{market_id}/ai-analysis")
def get_ai_analysis(
    market_id: str,
    research: bool = Query(default=False, description="Enable Tavily web research for news context"),
    force: bool = Query(default=False, description="Bypass cache and force a fresh LLM call")
):
    """
    Run AI analysis on a market.

    Responses are cached per (market_id, research flag) for ANALYSIS_CACHE_TTL seconds (1 hour).
    Use ?force=true to bypass the cache and trigger a fresh LLM call regardless of age.

    Set ?research=true to include Tavily web search context (requires TAVILY_API_KEY).
    Set ?research=false (default) to skip web search and use price data only.
    """
    # Reject non-numeric market IDs — Polymarket IDs are always numeric
    if not MARKET_ID_RE.match(market_id):
        raise HTTPException(status_code=400, detail="Invalid market ID format.")

    research_flag = 1 if research else 0

    db = get_db()
    try:
        # ── Cache read ────────────────────────────────────────────────────────
        # Check for a fresh cached analysis before hitting the LLM.
        # The cache key is (market_id, research_used) so toggling web research
        # always produces a distinct, correctly-labelled result.
        if not force:
            cached = db.execute(
                """
                SELECT analysis, created_at
                FROM analyses
                WHERE market_id = ?
                  AND research_used = ?
                  AND created_at >= datetime('now', ? || ' seconds')
                """,
                (market_id, research_flag, f"-{ANALYSIS_CACHE_TTL}")
            ).fetchone()

            if cached:
                log.warning(f"Cache hit for market {market_id} (research={research})")
                return {
                    "analysis": cached["analysis"],
                    "research_used": research,
                    "cached": True,
                    "cached_at": cached["created_at"]
                }

        # ── Cache miss / forced refresh — run the LLM ─────────────────────
        market = db.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        market = dict(market)
        price_history = None

        if market.get("clob_token_id"):
            price_history = get_history_as_price_list(market["clob_token_id"])

        if not price_history:
            raw = db.execute(
                "SELECT prices FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 5",
                (market_id,)
            ).fetchall()
            price_history = [h['prices'] for h in raw]

        analysis = analyst.analyze_market_shift(
            market['question'],
            price_history,
            market['volume'],
            use_research=research
        )

        # ── Cache write ───────────────────────────────────────────────────────
        # INSERT OR REPLACE so a forced refresh or a post-TTL call overwrites
        # the stale row cleanly without leaving orphaned rows.
        db.execute(
            """
            INSERT OR REPLACE INTO analyses (market_id, research_used, analysis, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (market_id, research_flag, analysis)
        )
        db.commit()

        return {
            "analysis": analysis,
            "research_used": research,
            "cached": False,
            "cached_at": None,
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"LLM Analysis failed for {market_id}: {e}")
        raise HTTPException(status_code=500, detail="AI analysis failed.")
    finally:
        db.close()


class Target(BaseModel):
    address: str
    label: str

    @field_validator('address')
    @classmethod
    def validate_address(cls, v):
        v = v.strip()
        if not ADDRESS_RE.match(v):
            raise ValueError("Must be a 42-character 0x Ethereum address.")
        return v

    @field_validator('label')
    @classmethod
    def validate_label(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Label cannot be empty.")
        if len(v) > MAX_LABEL_LEN:
            raise ValueError(f"Label too long (max {MAX_LABEL_LEN} chars).")
        return v

@app.post("/watchlist")
def add_to_watchlist(target: Target):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO watch_list (address, label, added_at) VALUES (?, ?, datetime('now'))",
            (target.address, target.label)
        )
        db.commit()
        return {"status": "success", "resolved_address": target.address}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to add target: {e}")
        raise HTTPException(status_code=400, detail="This 0x address is already in your watchlist.")
    finally:
        db.close()

@app.get("/wallets/{address}/profile")
def profile_wallet_api(address: str):
    _validate_address(address)
    try:
        real_owner = unmask_proxy(address)

        from config import Config
        url = f"{Config.DATA_API}/trades?user={address}&limit=15"
        resp = requests.get(url, timeout=10)
        trades_data = resp.json() if resp.status_code == 200 else []

        simplified_trades = [
            f"Bought {t.get('side')} on '{t.get('title')}' for ${t.get('size')}"
            for t in trades_data
        ]
        profile = analyst.profile_wallet(address, real_owner, simplified_trades)

        return {"profile": profile, "real_owner": real_owner}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Profiling failed: {e}")
        raise HTTPException(status_code=500, detail="AI Profiling failed.")

@app.delete("/watchlist/{address}")
def remove_from_watchlist(address: str):
    _validate_address(address)
    db = get_db()
    try:
        db.execute("DELETE FROM watch_list WHERE address = ?", (address,))
        db.commit()
        return {"status": "deleted"}
    except Exception as e:
        log.error(f"Failed to delete target {address}: {e}")
        raise HTTPException(status_code=500, detail="Database error during deletion.")
    finally:
        db.close()
