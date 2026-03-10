import requests
import time
from config import Config
from db import get_db
from notifier import Notifier
from logger import get_logger

log = get_logger("Watcher")

# In-memory cache to prevent spamming webhooks with already-seen trades
seen_trades = set()

def watch_wallets():
    db = get_db()
    tracked = db.execute("SELECT address, label FROM watch_list").fetchall()
    db.close()

    notifier = Notifier()

    for row in tracked:
        address = row['address']
        label = row['label']
        
        url = f"{Config.DATA_API}/trades?user={address}&limit=5"
        
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                trades = resp.json()
                for trade in trades:
                    # Using transactionHash to uniquely identify a trade
                    trade_id = trade.get('transactionHash') 
                    
                    if trade_id and trade_id not in seen_trades:
                        seen_trades.add(trade_id)
                        
                        market_title = trade.get('title', 'Unknown Market')
                        msg = f"**Entity:** `{label}`\n**Proxy Wallet:** `{address}`\n**Action:** Traded on _{market_title}_"
                        
                        notifier.broadcast(msg, title="🐳 OSINT Target Activity")
        except Exception as e:
            log.error(f"Failed to fetch trades for {address}: {e}")
            
        time.sleep(1) # Polite API spacing

if __name__ == "__main__":
    print("Wallet Watcher active...")
    while True:
        watch_wallets()
        time.sleep(300) # Run every 5 minutes