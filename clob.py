import requests
import time
from operator import itemgetter
from logger import get_logger

log = get_logger("CLOB")

CLOB_BASE = "https://clob.polymarket.com"
DEFAULT_INTERVAL = "1d"
DEFAULT_FIDELITY = 60
CACHE_TTL = 60

_SSL_VERIFY = False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_price_cache: dict = {}


def _is_sorted(history: list) -> bool:
    if len(history) < 2:
        return True
    return history[0]["t"] <= history[-1]["t"]


def get_price_history(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY):
    cache_key = (clob_token_id, interval, fidelity)
    now = time.time()

    if cache_key in _price_cache:
        cached = _price_cache[cache_key]
        if now - cached["timestamp"] < CACHE_TTL:
            return cached["data"]

    try:
        resp = requests.get(
            f"{CLOB_BASE}/prices-history",
            params={"market": clob_token_id, "interval": interval, "fidelity": fidelity},
            timeout=10,
            verify=_SSL_VERIFY,
        )
        if resp.status_code != 200:
            log.warning(f"CLOB history returned {resp.status_code} for token {clob_token_id}")
            return None

        history = resp.json().get("history", [])
        if not history:
            return None

        if not _is_sorted(history):
            history = sorted(history, key=itemgetter("t"))

        _price_cache[cache_key] = {"data": history, "timestamp": now}
        return history

    except Exception as e:
        log.error(f"CLOB history fetch failed for token {clob_token_id}: {e}")
        return None


def get_shift(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> float | None:
    history = get_price_history(clob_token_id, interval=interval)
    if not history or len(history) < 2:
        return None
    return float(history[-1]["p"]) - float(history[0]["p"])


def get_history_as_price_list(clob_token_id: str, interval: str = DEFAULT_INTERVAL) -> list[float] | None:
    history = get_price_history(clob_token_id, interval=interval)
    if not history:
        return None
    return [float(h["p"]) for h in history]


def get_price_data(clob_token_id: str, interval: str = DEFAULT_INTERVAL, fidelity: int = DEFAULT_FIDELITY) -> dict | None:
    history = get_price_history(clob_token_id, interval=interval, fidelity=fidelity)
    if not history:
        return None
    prices = [float(h["p"]) for h in history]
    shift = (prices[-1] - prices[0]) if len(prices) >= 2 else None
    return {"history": history, "prices": prices, "shift": shift}


def get_orderbook(clob_token_id: str) -> dict | None:
    try:
        resp = requests.get(
            f"{CLOB_BASE}/book",
            params={"token_id": clob_token_id},
            timeout=10,
            verify=_SSL_VERIFY,
        )
        if resp.status_code != 200:
            log.warning(f"CLOB book returned {resp.status_code} for token {clob_token_id}")
            return None
        return resp.json()
    except Exception as e:
        log.error(f"CLOB orderbook fetch failed for token {clob_token_id}: {e}")
        return None


def analyze_orderbook_depth(clob_token_id: str) -> dict | None:
    book = get_orderbook(clob_token_id)
    if not book:
        return None

    bids = book.get("bids", []) or []
    asks = book.get("asks", []) or []

    def _sum_side(orders):
        total_size = 0.0
        total_value = 0.0
        levels = 0
        for o in orders:
            try:
                size = float(o.get("size", 0))
                price = float(o.get("price", 0))
                total_size += size
                total_value += size * price
                levels += 1
            except (TypeError, ValueError):
                continue
        return {"total_size": total_size, "total_value": total_value, "levels": levels}

    bid_analysis = _sum_side(bids)
    ask_analysis = _sum_side(asks)

    bid_liquidity = bid_analysis["total_value"]
    ask_liquidity = ask_analysis["total_value"]

    if bid_liquidity + ask_liquidity > 0:
        bid_pct = round((bid_liquidity / (bid_liquidity + ask_liquidity)) * 100, 1)
    else:
        bid_pct = 50.0

    imbalance = bid_liquidity - ask_liquidity
    if abs(bid_liquidity + ask_liquidity) > 0:
        imbalance_ratio = round(imbalance / (bid_liquidity + ask_liquidity), 3)
    else:
        imbalance_ratio = 0.0

    largest_bid = 0.0
    largest_ask = 0.0
    for o in bids:
        try:
            s = float(o.get("size", 0)) * float(o.get("price", 0))
            if s > largest_bid:
                largest_bid = s
        except (TypeError, ValueError):
            pass
    for o in asks:
        try:
            s = float(o.get("size", 0)) * float(o.get("price", 0))
            if s > largest_ask:
                largest_ask = s
        except (TypeError, ValueError):
            pass

    wall_threshold = max(largest_bid, largest_ask) * 0.5
    bid_walls = sum(1 for o in bids if _order_value(o) >= wall_threshold)
    ask_walls = sum(1 for o in asks if _order_value(o) >= wall_threshold)

    spread = None
    best_bid = None
    best_ask = None
    try:
        bid_prices = sorted([float(o["price"]) for o in bids if o.get("price")], reverse=True)
        ask_prices = sorted([float(o["price"]) for o in asks if o.get("price")])
        if bid_prices and ask_prices:
            best_bid = bid_prices[0]
            best_ask = ask_prices[0]
            spread = round(best_ask - best_bid, 4)
    except (TypeError, ValueError, IndexError):
        pass

    return {
        "bid_liquidity_usd": round(bid_liquidity, 2),
        "ask_liquidity_usd": round(ask_liquidity, 2),
        "bid_depth_pct": bid_pct,
        "imbalance_ratio": imbalance_ratio,
        "spread": spread,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_levels": bid_analysis["levels"],
        "ask_levels": ask_analysis["levels"],
        "largest_bid_usd": round(largest_bid, 2),
        "largest_ask_usd": round(largest_ask, 2),
        "bid_walls": bid_walls,
        "ask_walls": ask_walls,
        "signal": _depth_signal(imbalance_ratio, bid_walls, ask_walls),
    }


def _order_value(o) -> float:
    try:
        return float(o.get("size", 0)) * float(o.get("price", 0))
    except (TypeError, ValueError):
        return 0.0


def _depth_signal(imbalance: float, bid_walls: int, ask_walls: int) -> str:
    if imbalance > 0.3:
        return "BUYING_PRESSURE"
    elif imbalance < -0.3:
        return "SELLING_PRESSURE"
    elif bid_walls > ask_walls + 2:
        return "BID_WALL_SUPPORT"
    elif ask_walls > bid_walls + 2:
        return "ASK_WALL_RESISTANCE"
    return "NEUTRAL"


def clear_cache():
    global _price_cache
    _price_cache = {}
