import requests
from config import Config
from logger import get_logger

log = get_logger("Notifier")

class Notifier:
    def __init__(self):
        self.discord_url = Config.DISCORD_WEBHOOK_URL
        self.tg_token = Config.TELEGRAM_BOT_TOKEN
        self.tg_chat_id = Config.TELEGRAM_CHAT_ID

    def send_discord(self, message: str, title: str = "PolySINT Alert"):
        if not self.discord_url:
            return
        
        payload = {
            "embeds":[
                {
                    "title": title,
                    "description": message,
                    "color": 16711680  # Alert Red
                }
            ]
        }
        try:
            resp = requests.post(self.discord_url, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            log.error(f"Discord broadcast failed: {e}")

    def send_telegram(self, message: str, title: str = "PolySINT Alert"):
        if not self.tg_token or not self.tg_chat_id:
            return
        
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        formatted_message = f"*{title}*\n\n{message}"
        
        payload = {
            "chat_id": self.tg_chat_id,
            "text": formatted_message,
            "parse_mode": "Markdown"
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            log.error(f"Telegram broadcast failed: {e}")

    def broadcast(self, message: str, title: str = "PolySINT Alert"):
        """Pushes actionable OSINT to all configured external endpoints."""
        self.send_discord(message, title)
        self.send_telegram(message, title)
        # Fallback console print
        print(f"\n[{title}]\n{message}\n")