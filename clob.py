import requests
from logger import get_logger

log = get_logger("CLOB")

CLOB_BASE = "https://clob.polymarket.com"

# How far back to look when calculating shift.
# "1d" gives a meaningful window even on a freshly restarted instance.
# Options: "1h", "6h", "1d", "1w", "max"
DEFAULT_INTERVAL = "1d"

# Resolution in minutes — 60 gives ~24 data points over 1d, enough for trend without hammering the API
DEFAULT_FIDELITY = 60

# Polymarket's CLOB endpoint uses a self-signed cert in its chain — disable verification
_SSL_VERIFY = False

# Suppress the urllib3 warning that fires when verify=False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY):
    """
    Fetches historical price data for a CLOB token from Polymarket.
    Returns a list of {"t": unix_timestamp, "p": price} dicts, oldest first.
    Returns None if the request fails.
    """
    try:
        resp = requests.get(
            f"{CLOB_BASE}/prices-history",
            params={
                "market": clob_token_id,
                "interval": interval,
                "fidelity": fidelity,
            },
            timeout=10,
            verify=_SSL_VERIFY,
        )
        if resp.status_code != 200:
            log.warning(f"CLOB history returned {resp.status_code} for token {clob_token_id}")
            return None

        history = resp.json().get("history", [])
        if not history:
            return None

        return sorted(history, key=lambda x: x["t"])

    except Exception as e:
        log.error(f"CLOB history fetch failed for token {clob_token_id}: {e}")
        return None


def get_shift(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> float | None:
    """
    Returns the price shift (as a float, e.g. 0.12 = 12%) over the given interval.
    Compares the oldest and newest data points in the history window.
    Returns None if history is unavailable or too short.
    """
    history = get_price_history(clob_token_id, interval=interval)
    if not history or len(history) < 2:
        return None

    price_then = float(history[0]["p"])
    price_now = float(history[-1]["p"])
    return price_now - price_then


def get_history_as_price_list(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> list[float] | None:
    """
    Returns a flat list of prices oldest-to-newest, suitable for passing to the LLM analyst.
    """
    history = get_price_history(clob_token_id, interval=interval)
    if not history:
        return None
    return [float(h["p"]) for h in history]
