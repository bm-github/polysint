import sqlite3
from config import Config
from logger import get_logger

log = get_logger("Database")

def get_db():
    try:
        conn = sqlite3.connect(Config.DB_NAME)
        conn.row_factory = sqlite3.Row
        # This allows multiple readers and one writer to coexist
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn
    except Exception as e:
        log.critical(f"Database connection failed: {e}")
        raise

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Markets Table — clob_token_id stores the YES outcome token for CLOB history lookups
    cursor.execute('''CREATE TABLE IF NOT EXISTS markets 
        (id TEXT PRIMARY KEY, question TEXT, outcomes TEXT, volume REAL, created_at TEXT, clob_token_id TEXT)''')

    # Migrate existing deployments: add clob_token_id column if it doesn't exist yet
    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(markets)").fetchall()]
    if "clob_token_id" not in existing_columns:
        cursor.execute("ALTER TABLE markets ADD COLUMN clob_token_id TEXT")
        log.warning("Migrated markets table: added clob_token_id column")

    # Snapshots Table — kept for fallback if CLOB history is unavailable
    cursor.execute('''CREATE TABLE IF NOT EXISTS snapshots 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, market_id TEXT, timestamp DATETIME, prices TEXT, volume REAL)''')

    # Watchlist Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS watch_list 
        (address TEXT PRIMARY KEY, label TEXT, added_at DATETIME)''')

    # Analyses Cache Table
    # Stores LLM-generated intelligence briefs with a TTL so repeated dashboard
    # requests for the same market don't burn a fresh API call every time.
    # research_used distinguishes cached results produced with/without Tavily,
    # so toggling web research always triggers a fresh analysis.
    cursor.execute('''CREATE TABLE IF NOT EXISTS analyses
        (
            market_id    TEXT    NOT NULL,
            research_used INTEGER NOT NULL DEFAULT 0,  -- 0 = false, 1 = true
            analysis     TEXT    NOT NULL,
            created_at   DATETIME NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (market_id, research_used)
        )''')

    conn.commit()
    conn.close()
