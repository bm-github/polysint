import requests
import json
import time
from datetime import datetime
from config import Config
from db import get_db, init_db
from logger import get_logger

log = get_logger("Harvester")


def extract_first_price(outcome_prices):
    """
    Safely extracts the first (YES) outcome price from whatever shape Gamma returns.
    Handles:
      - Already a list of floats/strings: ["0.5", "0.5"]
      - Double-encoded string: "[['0.5', '0.5']]"
      - Nested list: [["0.5", "0.5"]]
    Returns a JSON string of a flat list of strings, e.g. '["0.5", "0.5"]'.
    Returns '[]' on any failure.
    """
    try:
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)

        if not outcome_prices:
            return '[]'

        # Unwrap nested list if needed: [["0.5", "0.5"]] -> ["0.5", "0.5"]
        first = outcome_prices[0]
        if isinstance(first, list):
            outcome_prices = first

        # At this point we expect a flat list of price strings/floats
        # Validate each element is float-castable before storing
        validated = []
        for p in outcome_prices:
            try:
                float(p)
                validated.append(str(p))
            except (TypeError, ValueError):
                pass  # skip malformed entries

        return json.dumps(validated)

    except Exception as e:
        log.warning(f"Failed to parse outcomePrices '{outcome_prices}': {e}")
        return '[]'


def fetch_active_markets(session):
    """Paginates through the Polymarket API to get all active markets."""
    print(f"[{datetime.now()}] Fetching active markets from Polymarket...")
    all_markets = []
    limit = 100
    offset = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    session = requests.Session()
    session.headers.update(headers)

    while True:
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset
        }

        try:
            response = session.get(Config.GAMMA_API, params=params, timeout=15)

            if response.status_code == 429:
                print(f"Rate limited at offset {offset}. Sleeping for 10 seconds...")
                time.sleep(10)
                continue

            if response.status_code != 200:
                print(f"Error fetching data at offset {offset}: HTTP {response.status_code}")
                break

            data = response.json()
            if not data:
                break

            all_markets.extend(data)
            offset += limit

            if offset % 1000 == 0:
                print(f" -> Fetched {offset} markets...")

            time.sleep(0.5)

        except requests.exceptions.SSLError:
            print(f"\n[!] SSL Error at offset {offset}. Try adding verify=False to session.get()")
            break

        except Exception as e:
            log.warning(f"Network glitch at offset {offset}: {e}")
            print(f"\n[!] Network glitch at offset {offset}: {e}. Retrying in 5 seconds...")
            time.sleep(5)
            continue

    print(f"[{datetime.now()}] Successfully fetched {len(all_markets)} active markets.")
    return all_markets


def process_and_save(markets):
    db = get_db()
    cursor = db.cursor()
    current_time = datetime.now().isoformat()

    for market in markets:
        outcomes_json = json.dumps(market.get("outcomes", []))

        # Normalise outcomePrices into a clean flat JSON array before storing
        prices_json = extract_first_price(market.get("outcomePrices", []))

        # clobTokenIds comes back as a stringified JSON array e.g. '["111...","222..."]'
        # Index 0 is the YES outcome token used for CLOB price history lookups
        clob_token_id = None
        raw_clob = market.get("clobTokenIds")
        if raw_clob:
            try:
                token_ids = json.loads(raw_clob) if isinstance(raw_clob, str) else raw_clob
                if token_ids and len(token_ids) > 0:
                    clob_token_id = token_ids[0]
            except Exception as e:
                log.warning(f"Failed to parse clobTokenIds for market {market.get('id')}: {e}")

        # INSERT OR REPLACE so clob_token_id gets backfilled on restarts.
        # COALESCE preserves the original created_at timestamp.
        cursor.execute('''
            INSERT OR REPLACE INTO markets (id, question, outcomes, volume, created_at, clob_token_id)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM markets WHERE id = ?), ?), ?)
        ''', (
            market.get("id"),
            market.get("question"),
            outcomes_json,
            float(market.get("volume", 0)),
            market.get("id"),
            current_time,
            clob_token_id
        ))

        cursor.execute('''
            INSERT INTO snapshots (market_id, timestamp, prices, volume)
            VALUES (?, ?, ?, ?)
        ''', (market.get("id"), current_time, prices_json, float(market.get("volume", 0))))

    db.commit()
    db.close()


if __name__ == "__main__":
    init_db()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })

    try:
        while True:
            data = fetch_active_markets(session)
            process_and_save(data)
            time.sleep(900)
    except KeyboardInterrupt:
        print("Stopped.")
