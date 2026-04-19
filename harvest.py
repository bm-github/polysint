import json
import time
from datetime import datetime, timezone
import requests
from config import Config
from db import get_db, init_db
from logger import get_logger

log = get_logger("Harvester")

HARVEST_INTERVAL = 900  # 15 minutes
REQUEST_TIMEOUT = 30
PAGINATION_LIMIT = 100
MAX_RETRIES = 3
RETRY_BACKOFF = 10

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_first_price(outcome_prices):
    try:
        if outcome_prices is None:
            return '[]'

        if isinstance(outcome_prices, str):
            outcome_prices = outcome_prices.strip()
            if not outcome_prices:
                return '[]'
            try:
                outcome_prices = json.loads(outcome_prices)
            except json.JSONDecodeError:
                log.warning(f"outcomePrices is not valid JSON: {repr(outcome_prices)[:100]}")
                return '[]'

        if outcome_prices is None:
            return '[]'

        if not isinstance(outcome_prices, list):
            log.warning(f"outcomePrices is not a list after parsing: {type(outcome_prices).__name__}")
            return '[]'

        if not outcome_prices:
            return '[]'

        depth = 0
        while outcome_prices and isinstance(outcome_prices[0], list) and depth < 10:
            outcome_prices = outcome_prices[0]
            depth += 1

        if not outcome_prices:
            return '[]'

        validated = []
        for item in outcome_prices:
            price = None
            if isinstance(item, dict):
                price = item.get('price') or item.get('p')
            elif isinstance(item, (str, int, float)):
                price = item
            elif isinstance(item, list) and len(item) == 1:
                price = item[0]

            if price is not None:
                try:
                    float(price)
                    validated.append(str(price))
                except (TypeError, ValueError):
                    pass

        return json.dumps(validated)

    except Exception as e:
        preview = repr(outcome_prices)[:100] if outcome_prices else 'None'
        log.warning(f"Failed to parse outcomePrices '{preview}': {e}")
        return '[]'


def _extract_clob_token_id(market_data: dict) -> str | None:
    clob_id = market_data.get("clobTokenId")
    if clob_id:
        return clob_id

    tokens = market_data.get("tokens")
    if isinstance(tokens, list) and tokens:
        first = tokens[0]
        if isinstance(first, dict):
            return first.get("tokenID") or first.get("tokenId") or first.get("token_id")
        if isinstance(first, str):
            return first

    outcomes_str = market_data.get("outcomePrices")
    if outcomes_str and not clob_id:
        try:
            parsed = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            if isinstance(parsed, list) and len(parsed) > 0:
                pass
        except Exception:
            pass

    return None


def fetch_gamma_api(offset=0):
    params = {
        "limit": PAGINATION_LIMIT,
        "offset": offset,
        "active": "true",
        "closed": "false",
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(
                Config.GAMMA_API,
                params=params,
                headers=BROWSER_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            if resp.status_code == 429:
                log.warning(f"Rate limited (429). Backing off for {RETRY_BACKOFF}s...")
                time.sleep(RETRY_BACKOFF)
                continue

            if resp.status_code == 403:
                log.warning("Cloudflare 403 — consider rotating proxy or updating headers.")
                time.sleep(RETRY_BACKOFF)
                continue

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.RequestException as e:
            log.error(f"Gamma API request failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF)

    return []


def harvest_cycle():
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    total_new = 0
    total_updated = 0
    total_snapshots = 0
    offset = 0

    while True:
        markets = fetch_gamma_api(offset=offset)

        if not markets:
            break

        for m in markets:
            market_id = m.get("id") or m.get("conditionId")
            if not market_id:
                continue

            question = m.get("question", "Unknown Market")
            outcomes = m.get("outcomes", "[]")

            if isinstance(outcomes, list):
                outcomes = json.dumps(outcomes)

            volume = m.get("volume") or m.get("volumeNum") or 0
            try:
                volume = float(volume)
            except (TypeError, ValueError):
                volume = 0.0

            prices_raw = m.get("outcomePrices") or m.get("outcomePricesMapped")
            prices_json = extract_first_price(prices_raw)

            clob_token_id = _extract_clob_token_id(m)

            existing = db.execute(
                "SELECT id, clob_token_id FROM markets WHERE id = ?",
                (str(market_id),)
            ).fetchone()

            if existing:
                update_fields = ["volume = ?", "updated_at = ?"]
                update_params = [volume, now]

                if clob_token_id and not existing["clob_token_id"]:
                    update_fields.append("clob_token_id = ?")
                    update_params.append(clob_token_id)

                update_params.append(str(market_id))
                db.execute(
                    f"UPDATE markets SET {', '.join(update_fields)} WHERE id = ?",
                    update_params
                )
                total_updated += 1
            else:
                db.execute(
                    """INSERT INTO markets (id, question, outcomes, volume, created_at, clob_token_id)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (str(market_id), question, outcomes, volume, now, clob_token_id)
                )
                total_new += 1

            if prices_json and prices_json != '[]':
                try:
                    db.execute(
                        "INSERT INTO snapshots (market_id, timestamp, prices, volume) VALUES (?, ?, ?, ?)",
                        (str(market_id), now, prices_json, volume)
                    )
                    total_snapshots += 1
                except Exception as e:
                    log.warning(f"Failed to insert snapshot for market {market_id}: {e}")

        db.commit()

        if len(markets) < PAGINATION_LIMIT:
            break

        offset += PAGINATION_LIMIT
        time.sleep(1)

    db.close()
    print(f"[Harvester] Cycle complete — {total_new} new, {total_updated} updated, {total_snapshots} snapshots at {now}")
    return total_new, total_updated, total_snapshots


def backfill_clob_token_ids():
    db = get_db()
    missing = db.execute(
        "SELECT id FROM markets WHERE clob_token_id IS NULL"
    ).fetchall()

    if not missing:
        db.close()
        return

    print(f"[Harvester] Backfilling CLOB token IDs for {len(missing)} markets...")
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    backfilled = 0

    for row in missing:
        market_id = row["id"]
        try:
            resp = session.get(
                f"{Config.GAMMA_API}/{market_id}",
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                clob_id = _extract_clob_token_id(data)
                if clob_id:
                    db.execute(
                        "UPDATE markets SET clob_token_id = ? WHERE id = ?",
                        (clob_id, market_id)
                    )
                    backfilled += 1
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Backfill failed for market {market_id}: {e}")

    db.commit()
    db.close()
    print(f"[Harvester] Backfilled {backfilled}/{len(missing)} CLOB token IDs")


if __name__ == "__main__":
    init_db()
    print(f"Data Harvester active — polling every {HARVEST_INTERVAL // 60} minutes")

    try:
        db = get_db()
        existing = db.execute("SELECT COUNT(*) as cnt FROM markets").fetchone()
        db.close()
        if existing["cnt"] > 0:
            backfill_clob_token_ids()
    except Exception:
        pass

    while True:
        try:
            harvest_cycle()
        except Exception as e:
            log.error(f"Harvest cycle failed: {e}")
        time.sleep(HARVEST_INTERVAL)
