import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_NAME = "polysint_core.db"

    # Polymarket specific endpoints
    GAMMA_API = "https://gamma-api.polymarket.com/markets"
    DATA_API = "https://data-api.polymarket.com"

    # Blockchain RPC
    RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

    # LLM
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_BASE_URL = os.getenv("LLM_API_BASE_URL")
    LLM_MODEL = os.getenv("ANALYSIS_MODEL")

    # Webhook Configurations
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # Web Research (Tavily)
    # Set ENABLE_WEB_RESEARCH=true in .env to enable for background daemons.
    # Defaults to False — avoids 400 errors if TAVILY_API_KEY is missing/broken.
    ENABLE_WEB_RESEARCH = os.getenv("ENABLE_WEB_RESEARCH", "false").lower() == "true"
