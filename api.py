import time
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from concurrent.futures import ThreadPoolExecutor, as_completed
from db import get_db, init_db
from analyst import PolyAnalyst
from utils import unmask_proxy, unmask_proxy_full
from logger import get_logger
from clob import get_shift, get_price_history, get_history_as_price_list, DEFAULT_INTERVAL, analyze_orderbook_depth
from pydantic import BaseModel, field_validator
import re
import requests as http_requests
import json

from config import Config

log = get_logger("API")

app = FastAPI(title="PolySINT Core Engine")
analyst = PolyAnalyst()

MIN_VOLUME_FOR_CLOB = 5000
CLOB_WORKERS = 20
ANALYSIS_CACHE_TTL = 3600

MAX_SEARCH_LEN = 200
MAX_LABEL_LEN = 80
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
MARKET_ID_RE = re.compile(r'^[0-9]+$')

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = Config.RATE_LIMIT_PER_MINUTE


@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    requests_ts = _rate_limit_store[client_ip]
    _rate_limit_store[client_ip] = [t for t in requests_ts if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
        return Response(content='{"detail":"Rate limit exceeded"}', status_code=429, media_type="application/json")
    _rate_limit_store[client_ip].append(now)
    response = await call_next(request)
    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "frame-ancestors 'none'"
    )
    return response


@app.middleware("http")
async def api_auth(request: Request, call_next):
    if not Config.API_AUTH_ENABLED:
        return await call_next(request)

    public_paths = {"/", "/static/"}
    path = request.url.path

    if path == "/" or path.startswith("/static/"):
        return await call_next(request)

    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if api_key != Config.API_KEY:
        return Response(content='{"detail":"Unauthorized"}', status_code=401, media_type="application/json")

    return await call_next(request)


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")


def _validate_address(address: str) -> str:
    if not ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=400,
            detail="Invalid address. Must be a 42-character 0x Ethereum address."
        )
    return address


def _enrich_market(m: dict) -> dict | None:
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


@app.get("/wallets/{address}/unmask/full")
def unmask_wallet_full(address: str):
    _validate_address(address)
    result = unmask_proxy_full(address)
    return result


@app.get("/markets/{market_id}/orderbook")
def get_orderbook_analysis(market_id: str):
    if not MARKET_ID_RE.match(market_id):
        raise HTTPException(status_code=400, detail="Invalid market ID format.")

    db = get_db()
    try:
        market = db.execute("SELECT clob_token_id, question FROM markets WHERE id = ?", (market_id,)).fetchone()
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")
        if not market["clob_token_id"]:
            raise HTTPException(status_code=400, detail="No CLOB token ID for this market.")
    finally:
        db.close()

    depth = analyze_orderbook_depth(market["clob_token_id"])
    if not depth:
        raise HTTPException(status_code=502, detail="Failed to fetch orderbook from CLOB.")

    return {"market_id": market_id, "question": market["question"], "depth": depth}


@app.get("/wallets/{address}/alerts")
def get_entity_alerts(address: str, limit: int = 20):
    _validate_address(address)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM entity_alerts WHERE proxy_address = ? ORDER BY created_at DESC LIMIT ?",
            (address, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


@app.get("/wallets/{address}/trades")
def get_entity_trades(address: str, limit: int = 50):
    _validate_address(address)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM entity_trades WHERE proxy_address = ? ORDER BY timestamp DESC LIMIT ?",
            (address, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


@app.get("/wallets/{address}/linked")
def get_linked_entities(address: str):
    _validate_address(address)
    db = get_db()
    try:
        eoa_row = db.execute(
            "SELECT human_eoa FROM linked_entities WHERE proxy_wallet = ?", (address,)
        ).fetchone()

        if not eoa_row:
            return {"proxy": address, "linked": []}

        eoa = eoa_row["human_eoa"]
        linked = db.execute(
            "SELECT * FROM linked_entities WHERE human_eoa = ?", (eoa,)
        ).fetchall()
        return {"proxy": address, "eoa": eoa, "linked": [dict(r) for r in linked]}
    finally:
        db.close()


@app.get("/markets/{market_id}/ai-analysis")
def get_ai_analysis(
    market_id: str,
    research: bool = Query(default=False, description="Enable Tavily web research for news context"),
    force: bool = Query(default=False, description="Bypass cache and force a fresh LLM call")
):
    if not MARKET_ID_RE.match(market_id):
        raise HTTPException(status_code=400, detail="Invalid market ID format.")

    research_flag = 1 if research else 0

    db = get_db()
    try:
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

        url = f"{Config.DATA_API}/trades?user={address}&limit=15"
        resp = http_requests.get(url, timeout=10)
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
