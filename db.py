import sqlite3
import time
from config import Config
from logger import get_logger

log = get_logger("Database")

DB_LOCKED_RETRIES = 5
DB_LOCKED_BACKOFF = 0.5


def get_db():
    try:
        conn = sqlite3.connect(Config.DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn
    except Exception as e:
        log.critical(f"Database connection failed: {e}")
        raise


def db_execute_retry(conn, sql, params=None, commit=True):
    for attempt in range(DB_LOCKED_RETRIES):
        try:
            cursor = conn.execute(sql, params or ())
            if commit:
                conn.commit()
            return cursor
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < DB_LOCKED_RETRIES - 1:
                wait = DB_LOCKED_BACKOFF * (2 ** attempt)
                log.warning(f"DB locked, retrying in {wait:.1f}s (attempt {attempt + 1}/{DB_LOCKED_RETRIES})")
                time.sleep(wait)
            else:
                raise
    return None


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS markets
        (id TEXT PRIMARY KEY, question TEXT, outcomes TEXT, volume REAL,
         created_at TEXT, clob_token_id TEXT, updated_at TEXT)''')

    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(markets)").fetchall()]
    if "clob_token_id" not in existing_columns:
        cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_id TEXT")
        log.warning("Migrated markets table: added clob_token_id column")
    if "updated_at" not in existing_columns:
        cursor.execute("ALTER TABLE markets ADD COLUMN updated_at TEXT")
        log.warning("Migrated markets table: added updated_at column")

    cursor.execute('''CREATE TABLE IF NOT EXISTS snapshots
        (id INTEGER PRIMARY KEY AUTOINCREMENT, market_id TEXT,
         timestamp DATETIME, prices TEXT, volume REAL)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS watch_list
        (address TEXT PRIMARY KEY, label TEXT, added_at DATETIME)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS analyses
        (
            market_id    TEXT    NOT NULL,
            research_used INTEGER NOT NULL DEFAULT 0,
            analysis     TEXT    NOT NULL,
            created_at   DATETIME NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (market_id, research_used)
        )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS seen_trades
        (tx_hash TEXT PRIMARY KEY, seen_at DATETIME DEFAULT (datetime('now')))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS linked_entities
        (human_eoa TEXT, proxy_wallet TEXT, first_seen DATETIME DEFAULT (datetime('now')),
         UNIQUE(human_eoa, proxy_wallet))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS entity_trades
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         proxy_address TEXT NOT NULL,
         tx_hash TEXT NOT NULL,
         market_title TEXT,
         side TEXT,
         size REAL,
         price REAL,
         timestamp DATETIME,
         recorded_at DATETIME DEFAULT (datetime('now')))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS entity_alerts
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         proxy_address TEXT NOT NULL,
         alert_type TEXT NOT NULL,
         message TEXT,
         created_at DATETIME DEFAULT (datetime('now')))''')

    _create_indexes(cursor)

    conn.commit()
    conn.close()


def _create_indexes(cursor):
    indexes = [
        ("idx_snapshots_market_ts", "CREATE INDEX IF NOT EXISTS idx_snapshots_market_ts ON snapshots(market_id, timestamp DESC)"),
        ("idx_entity_trades_proxy", "CREATE INDEX IF NOT EXISTS idx_entity_trades_proxy ON entity_trades(proxy_address, timestamp DESC)"),
        ("idx_entity_trades_tx", "CREATE INDEX IF NOT EXISTS idx_entity_trades_tx ON entity_trades(tx_hash)"),
        ("idx_linked_entities_eoa", "CREATE INDEX IF NOT EXISTS idx_linked_entities_eoa ON linked_entities(human_eoa)"),
        ("idx_linked_entities_proxy", "CREATE INDEX IF NOT EXISTS idx_linked_entities_proxy ON linked_entities(proxy_wallet)"),
        ("idx_seen_trades_hash", "CREATE INDEX IF NOT EXISTS idx_seen_trades_hash ON seen_trades(tx_hash)"),
        ("idx_markets_clob_token", "CREATE INDEX IF NOT EXISTS idx_markets_clob_token ON markets(clob_token_id)"),
        ("idx_entity_alerts_proxy", "CREATE INDEX IF NOT EXISTS idx_entity_alerts_proxy ON entity_alerts(proxy_address, created_at DESC)"),
    ]

    for name, sql in indexes:
        try:
            cursor.execute(sql)
        except sqlite3.OperationalError:
            pass
