import json
import time
from datetime import datetime, timezone, timedelta
import requests
from config import Config
from db import get_db, init_db, db_execute_retry
from notifier import Notifier
from utils import unmask_proxy
from logger import get_logger

log = get_logger("Watcher")

WATCH_INTERVAL = 300  # 5 minutes
API_TIMEOUT = 10
TRADE_LIMIT = 20

TIER_RETAIL = "RETAIL"
TIER_WHALE = "WHALE"
TIER_MEGA = "MEGA-WHALE"

WHALE_THRESHOLD = 5_000
MEGA_THRESHOLD = 50_000

LEAD_WINDOW_MINUTES = 60


def _classify_trade_size(size) -> tuple:
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "UNKNOWN", 0.0
    if size >= MEGA_THRESHOLD:
        return TIER_MEGA, size
    elif size >= WHALE_THRESHOLD:
        return TIER_WHALE, size
    return TIER_RETAIL, size


def _is_trade_seen(db, tx_hash: str) -> bool:
    row = db.execute("SELECT 1 FROM seen_trades WHERE tx_hash = ?", (tx_hash,)).fetchone()
    return row is not None


def _mark_trade_seen(db, tx_hash: str):
    db_execute_retry(db, "INSERT OR IGNORE INTO seen_trades (tx_hash) VALUES (?)", (tx_hash,))


def _record_entity_trade(db, proxy_address, trade):
    tx_hash = trade.get("transactionHash")
    if not tx_hash:
        return

    size_val = trade.get("size") or trade.get("amount")
    price_val = trade.get("price")
    ts = trade.get("timestamp") or trade.get("createdAt")

    db_execute_retry(
        db,
        """INSERT OR IGNORE INTO entity_trades
           (proxy_address, tx_hash, market_title, side, size, price, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            proxy_address,
            tx_hash,
            trade.get("title", "Unknown Market"),
            trade.get("side"),
            size_val,
            price_val,
            ts,
        ),
        commit=False,
    )


def _auto_unmask(db, proxy_address: str) -> str | None:
    existing = db.execute(
        "SELECT human_eoa FROM linked_entities WHERE proxy_wallet = ?",
        (proxy_address,),
    ).fetchone()

    if existing:
        return existing["human_eoa"]

    try:
        real_eoa = unmask_proxy(proxy_address)
        if real_eoa and real_eoa.startswith("0x"):
            db_execute_retry(
                db,
                "INSERT OR IGNORE INTO linked_entities (human_eoa, proxy_wallet) VALUES (?, ?)",
                (real_eoa, proxy_address),
                commit=False,
            )
            return real_eoa
    except Exception as e:
        log.warning(f"Auto-unmask failed for {proxy_address}: {e}")

    return None


def _check_cross_linked(db, proxy_address: str, real_eoa: str, notifier: Notifier):
    if not real_eoa or not real_eoa.startswith("0x"):
        return

    linked = db.execute(
        "SELECT proxy_wallet FROM linked_entities WHERE human_eoa = ? AND proxy_wallet != ?",
        (real_eoa, proxy_address),
    ).fetchall()

    if linked:
        other_proxies = [r["proxy_wallet"] for r in linked]
        msg = (
            f"**Sybil Cluster Detected!**\n"
            f"Real EOA: `{real_eoa}`\n"
            f"Known proxies:\n"
            f"  - `{proxy_address}` (current)\n"
        )
        for p in other_proxies:
            msg += f"  - `{p}`\n"

        msg += (
            f"\nThis entity controls **{len(other_proxies) + 1}** proxy wallets on Polymarket. "
            f"This may indicate coordinated trading or position splitting to avoid detection."
        )
        notifier.broadcast(msg, title="🔗 Sybil Cluster Alert")

        db_execute_retry(
            db,
            "INSERT INTO entity_alerts (proxy_address, alert_type, message) VALUES (?, ?, ?)",
            (proxy_address, "SYBIL_CLUSTER", msg),
            commit=False,
        )


def _check_leading_trades(db, proxy_address: str, label: str, trade_data: dict, notifier: Notifier):
    market_title = trade_data.get("title")
    trade_ts_str = trade_data.get("timestamp") or trade_data.get("createdAt")
    if not trade_ts_str or not market_title:
        return

    try:
        if isinstance(trade_ts_str, (int, float)):
            trade_dt = datetime.fromtimestamp(trade_ts_str, tz=timezone.utc)
        else:
            trade_ts_str = trade_ts_str.replace("Z", "+00:00")
            trade_dt = datetime.fromisoformat(trade_ts_str)
            if trade_dt.tzinfo is None:
                trade_dt = trade_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return

    market_row = db.execute(
        "SELECT id, clob_token_id FROM markets WHERE question LIKE ?",
        (f"%{market_title[:50]}%",),
    ).fetchone()

    if not market_row or not market_row["clob_token_id"]:
        return

    from clob import get_price_history

    try:
        history = get_price_history(market_row["clob_token_id"])
    except Exception:
        return

    if not history or len(history) < 2:
        return

    for point in history:
        try:
            point_t = float(point.get("t", 0))
            point_dt = datetime.fromtimestamp(point_t, tz=timezone.utc)
            price_after = float(point.get("p", 0))

            if trade_dt <= point_dt <= trade_dt + timedelta(minutes=LEAD_WINDOW_MINUTES):
                before_points = [p for p in history if float(p.get("t", 0)) < point_t]
                if before_points:
                    price_before = float(before_points[-1].get("p", 0))
                    shift = abs(price_after - price_before)

                    if shift >= 0.05:
                        side = trade_data.get("side", "UNKNOWN")
                        size = trade_data.get("size", "UNKNOWN")
                        msg = (
                            f"**Potential Leading Trade Detected!**\n"
                            f"Entity: `{label}` (`{proxy_address}`)\n"
                            f"Trade: {side} ${size} on _{market_title}_\n"
                            f"Market moved **{shift * 100:.1f}%** within {LEAD_WINDOW_MINUTES} minutes of their trade.\n"
                            f"Trade time: {trade_dt.strftime('%H:%M:%S UTC')}\n"
                        )
                        notifier.broadcast(msg, title="⏱️ Leading Trade Signal")

                        db_execute_retry(
                            db,
                            "INSERT INTO entity_alerts (proxy_address, alert_type, message) VALUES (?, ?, ?)",
                            (proxy_address, "LEADING_TRADE", msg),
                            commit=False,
                        )
                break
        except (ValueError, TypeError):
            continue


def watch_wallets():
    db = get_db()
    tracked = db.execute("SELECT address, label FROM watch_list").fetchall()
    notifier = Notifier()

    for row in tracked:
        address = row["address"]
        label = row["label"]

        real_eoa = _auto_unmask(db, address)
        if real_eoa and real_eoa.startswith("0x"):
            _check_cross_linked(db, address, real_eoa, notifier)

        url = f"{Config.DATA_API}/trades?user={address}&limit={TRADE_LIMIT}"

        try:
            resp = requests.get(url, timeout=API_TIMEOUT)
            if resp.status_code != 200:
                continue

            trades = resp.json()
            for trade in trades:
                tx_hash = trade.get("transactionHash")
                if not tx_hash:
                    continue

                if _is_trade_seen(db, tx_hash):
                    continue

                _mark_trade_seen(db, tx_hash)
                _record_entity_trade(db, address, trade)

                market_title = trade.get("title", "Unknown Market")
                side = trade.get("side", "UNKNOWN")
                size = trade.get("size") or trade.get("amount", "N/A")

                tier, size_float = _classify_trade_size(size)

                tier_emoji = {
                    TIER_MEGA: "🐋",
                    TIER_WHALE: "🐳",
                    TIER_RETAIL: "🐟",
                }.get(tier, "🐟")

                msg = (
                    f"{tier_emoji} **[{tier}] {label}**\n"
                    f"Proxy: `{address}`\n"
                )
                if real_eoa and real_eoa.startswith("0x"):
                    msg += f"EOA: `{real_eoa}`\n"
                msg += (
                    f"Action: **{side}** ${size} on _{market_title}_\n"
                    f"TX: `{tx_hash[:16]}…`"
                )

                notifier.broadcast(msg, title=f"{tier_emoji} OSINT Target Activity [{tier}]")

                _check_leading_trades(db, address, label, trade, notifier)

            db.commit()

        except Exception as e:
            log.error(f"Failed to fetch trades for {address}: {e}")

        time.sleep(1)

    db.close()


if __name__ == "__main__":
    init_db()
    print("Wallet Watcher active — with trade sizing, linked entity detection, and temporal analysis")
    while True:
        try:
            watch_wallets()
        except Exception as e:
            log.error(f"Watch cycle failed: {e}")
        time.sleep(WATCH_INTERVAL)
