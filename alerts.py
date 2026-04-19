import json
import time
from db import get_db, init_db
from notifier import Notifier
from logger import get_logger
from clob import get_shift, get_price_history, DEFAULT_INTERVAL

log = get_logger("Alerts")

# ─── Thresholds ───────────────────────────────────────────────────────────────

# Minimum 24h price shift to trigger an alert
ANOMALY_THRESHOLD = 0.10  # 10%

# Markets below this lifetime volume are ignored entirely —
# low-liquidity markets move 10%+ on single small trades and generate noise
MIN_ALERT_VOLUME = 5000

# Markets with a current YES probability above this or below its inverse are
# close to resolution. Their swings carry less signal and generate noise.
# e.g. 0.80 means: skip markets already sitting at >80% or <20%
NEAR_RESOLUTION_THRESHOLD = 0.80


def safe_float(val):
    """Returns float or None — never raises."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def scan_for_anomalies():
    init_db()
    db = get_db()
    markets = db.execute("SELECT id, question, volume, clob_token_id FROM markets").fetchall()
    db.close()

    notifier = Notifier()

    for m in markets:
        # ── Volume gate ──────────────────────────────────────────────────────
        # Reject $0 and low-volume markets before any CLOB call.
        # Volume in the DB is set at harvest time — stale or never-traded
        # markets can still shift 10%+ on single trades and are not actionable.
        market_volume = m['volume'] or 0
        if market_volume < MIN_ALERT_VOLUME:
            continue

        clob_token_id = m['clob_token_id']

        try:
            if clob_token_id:
                # ── Primary path: CLOB history ───────────────────────────────
                shift = get_shift(clob_token_id)

                if shift is None:
                    continue

                if abs(shift) >= ANOMALY_THRESHOLD:
                    # Get current price for context and the near-resolution check
                    history = get_price_history(clob_token_id)
                    if not history:
                        continue

                    current_price = float(history[-1]['p'])

                    # ── Near-resolution gate ──────────────────────────────────
                    # Skip markets already close to 100% or 0% — they are
                    # effectively settled and their remaining moves are noise.
                    if current_price >= NEAR_RESOLUTION_THRESHOLD or current_price <= (1 - NEAR_RESOLUTION_THRESHOLD):
                        log.warning(
                            f"Suppressed alert for '{m['question']}': "
                            f"price {current_price:.2f} is near resolution."
                        )
                        continue

                    direction = "📈" if shift > 0 else "📉"
                    current_price_str = f"{round(current_price * 100)}%"

                    msg = (
                        f"{direction} **{m['question']}**\n"
                        f"Shifted **{shift * 100:.1f}%** over the last {DEFAULT_INTERVAL} "
                        f"— now at **{current_price_str}**\n"
                        f"Volume: ${market_volume:,.0f}\n\n"
                        f"_Open the dashboard to run AI analysis on demand._"
                    )
                    notifier.broadcast(msg, title="🚨 Market Anomaly Detected")

            else:
                # ── Fallback: local snapshot comparison ──────────────────────
                db2 = get_db()
                history = db2.execute("""
                    SELECT prices FROM snapshots
                    WHERE market_id = ?
                    ORDER BY timestamp DESC LIMIT 2""", (m['id'],)).fetchall()
                db2.close()

                if len(history) < 2:
                    continue

                try:
                    prices_now = json.loads(history[0]['prices'])
                    prices_then = json.loads(history[1]['prices'])
                except (json.JSONDecodeError, TypeError):
                    log.warning(f"Malformed prices JSON in snapshots for market {m['id']}, skipping.")
                    continue

                if not prices_now or not prices_then:
                    continue

                now = safe_float(prices_now[0])
                then = safe_float(prices_then[0])

                if now is None or then is None:
                    log.warning(
                        f"Non-numeric price in snapshots for market {m['id']} "
                        f"(got '{prices_now[0]}' / '{prices_then[0]}'), skipping."
                    )
                    continue

                diff = now - then

                if abs(diff) >= ANOMALY_THRESHOLD:
                    # ── Near-resolution gate (snapshot fallback) ──────────────
                    if now >= NEAR_RESOLUTION_THRESHOLD or now <= (1 - NEAR_RESOLUTION_THRESHOLD):
                        log.warning(
                            f"Suppressed alert for '{m['question']}': "
                            f"price {now:.2f} is near resolution (snapshot fallback)."
                        )
                        continue

                    direction = "📈" if diff > 0 else "📉"
                    msg = (
                        f"{direction} **{m['question']}**\n"
                        f"Shifted **{diff * 100:.1f}%** (local snapshots)\n"
                        f"Volume: ${market_volume:,.0f}\n\n"
                        f"_Open the dashboard to run AI analysis on demand._"
                    )
                    notifier.broadcast(msg, title="🚨 Market Anomaly Detected")

        except Exception as e:
            log.error(f"Error scanning anomaly for {m['id']}: {e}")
            continue


if __name__ == "__main__":
    print(
        f"Anomaly Scanner active — "
        f"Threshold: {ANOMALY_THRESHOLD * 100:.0f}% over {DEFAULT_INTERVAL} | "
        f"Min volume: ${MIN_ALERT_VOLUME:,} | "
        f"Near-resolution cutoff: {NEAR_RESOLUTION_THRESHOLD * 100:.0f}%"
    )
    while True:
        scan_for_anomalies()
        time.sleep(300)  # Run every 5 minutes
