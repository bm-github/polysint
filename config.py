import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_NAME = "polysint_core.db"

    GAMMA_API = "https://gamma-api.polymarket.com/markets"
    DATA_API = "https://data-api.polymarket.com"

    RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_BASE_URL = os.getenv("LLM_API_BASE_URL")
    LLM_MODEL = os.getenv("ANALYSIS_MODEL")

    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"

    API_KEY = os.getenv("POLYSINT_API_KEY")
    API_AUTH_ENABLED = os.getenv("POLYSINT_API_KEY") is not None and os.getenv("POLYSINT_API_KEY") != ""

    RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

    WATCHER_LEAD_WINDOW_MINUTES = int(os.getenv("WATCHER_LEAD_WINDOW_MINUTES", "60"))
    WHALE_THRESHOLD = float(os.getenv("WHALE_THRESHOLD", "5000"))
    MEGA_THRESHOLD = float(os.getenv("MEGA_THRESHOLD", "50000"))
