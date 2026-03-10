# 🕵️‍♂️ PolySINT: Prediction Market OSINT Engine

**PolySINT** is an automated Open Source Intelligence (OSINT) platform designed to monitor Polymarket via the Polygon blockchain. It is built as a headless microservice architecture that identifies early warning signals, tracks insider trading behaviours, unmasks anonymous proxy wallets, and uses Large Language Models (LLMs) to provide cognitive forensic analysis of market anomalies.

## ✨ Features

* **Automated Harvester:** Scrapes and paginates Polymarket's Gamma API to track active markets and volume, running every 15 minutes. Automatically extracts CLOB token IDs for each market to enable real-time price history lookups.
* **CLOB Price History:** Fetches live 24-hour price history directly from `clob.polymarket.com` for enriched shift calculations, with local snapshot fallback if CLOB data is unavailable.
* **Anomaly Detection:** Monitors markets for probability shifts exceeding 10% over a 24-hour window. Triggers alerts via all configured notification channels.
* **AI Intelligence Briefs:** Uses LLMs (OpenAI/Claude via OpenRouter) to evaluate *why* a market is moving, with optional real-world news correlation via the Tavily search API (opt-in, off by default).
* **Entity Tracking (Whale Watcher):** Tracks tagged target wallets and unmasks Polymarket Gnosis Safe proxies to find the real human owner (EOA) via Polygon RPC calls.
* **Web Dashboard:** A live dark-mode UI showing top volatile markets, 24h shift indicators, anomaly highlights, and a full entity watchlist manager with AI profiling and wallet unmasking.
* **Notification Layer:** Pushes actionable intelligence to Discord and/or Telegram, plus a periodic health heartbeat every 6 hours.

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have **Python 3.9+** installed. You will also need:
- An API key for your preferred LLM (OpenAI, or any OpenAI-compatible provider such as OpenRouter for Claude)
- A **Tavily API key** for real-world news context — optional, see note below ([tavily.com](https://tavily.com))
- Optionally, webhooks for Discord and/or Telegram notifications

### 2. Installation
Clone the repository and install the required Python dependencies:

```bash
# Clone the repository
git clone https://github.com/bm-github/polysint.git
cd polysint

# Create a virtual environment (Recommended)
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# Install dependencies
pip install fastapi uvicorn requests python-dotenv openai web3
```

### 3. Environment Configuration
Create a `.env` file in the root directory of the project. PolySINT relies on this file to manage all secrets and feature flags.

```env
# Blockchain
POLYGON_RPC_URL="https://polygon-rpc.com"  # Or use your own Infura/Alchemy endpoint

# LLM / AI Analyst
# Standard OpenAI, or use OpenRouter to access Claude
LLM_API_KEY="your_llm_api_key_here"
LLM_API_BASE_URL="https://api.openai.com/v1"
ANALYSIS_MODEL="gpt-4o"

# Web Research via Tavily (Optional)
# Required only if ENABLE_WEB_RESEARCH=true
# TAVILY_API_KEY="your_tavily_api_key_here"

# Enable background daemons to use Tavily during anomaly analysis
# Defaults to false — avoids 400 errors if TAVILY_API_KEY is missing
# ENABLE_WEB_RESEARCH=false

# Notification Webhooks (Optional but recommended)
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
TELEGRAM_CHAT_ID="your_telegram_chat_id"
```

> **Note on Web Research:** `TAVILY_API_KEY` is optional. When `ENABLE_WEB_RESEARCH=true` is set, background daemons will fetch real-world news headlines to help the LLM classify market moves as Reactionary (news-driven) vs Suspicious (insider-driven). Web research can also be toggled per-request from the dashboard UI without affecting the daemon setting.

> **Note on Notifications:** If Discord or Telegram are left blank, the system safely skips them and prints alerts to the console only.

---

## ⚙️ Running the Engine

### Recommended: One-Command Launch (`start.py`)

The easiest way to run PolySINT is with the unified launcher, which starts all daemons as subprocesses, monitors their health, and sends a periodic heartbeat to your configured webhooks:

```bash
python start.py
```

This will:
1. Launch the **FastAPI server** on port **9000**
2. Launch the **Data Harvester**
3. Launch the **Anomaly Detector**
4. Launch the **Whale Watcher**
5. Send a boot notification to Discord/Telegram
6. Send a health check every **6 hours** (configurable via `HEARTBEAT_INTERVAL` in `start.py`)

Press `Ctrl+C` to safely shut down all processes.

---

### Alternative: Manual Launch (Separate Terminals)

If you prefer granular control, you can run each component individually using separate terminals, `tmux`, `screen`, or a process manager like PM2/Supervisor.

#### Step 1: Start the API (Core Interface & DB Init)
Starting the API automatically initialises the SQLite database schema.
```bash
uvicorn api:app --port 9000 --reload
```
The interactive API documentation is available at [http://localhost:9000/docs](http://localhost:9000/docs).  
The web dashboard is available at [http://localhost:9000](http://localhost:9000).

#### Step 2: Start the Data Harvester
Pulls active market data from Polymarket every 15 minutes, saves local snapshots, and backfills CLOB token IDs.
```bash
python harvest.py
```
> Wait for this script to complete at least one full run before starting the Anomaly Detector.

#### Step 3: Start the Anomaly Detector
Checks markets every 5 minutes. If a 24-hour CLOB price shift exceeds 10%, it broadcasts an intelligence alert via all configured webhooks.
```bash
python alerts.py
```

#### Step 4: Start the Whale Watcher
Monitors your watchlist wallets for new trades every 5 minutes.
```bash
python watcher.py
```

---

## 🌐 Web Dashboard

Once the API is running, open [http://localhost:9000](http://localhost:9000) to access the live dashboard.

**Features:**
- **Top Markets by Volume** — sorted by 24h volatility, with anomalies (≥10% shift) highlighted in red and warnings (≥5% shift) in amber
- **Real-time Odds** — current YES probability displayed under each market question
- **24h Shift** — directional price movement (↑/↓) calculated from CLOB history
- **Web Research Toggle** — enable or disable Tavily news context per analysis request, independent of the daemon setting
- **AI Analyze** — triggers a full LLM intelligence brief for any market on demand
- **Auto-Refresh** — markets automatically reload every 5 minutes with a live countdown
- **Entity Watchlist** — add, remove, and manage tracked wallets directly from the UI
- **Unmask** — resolves a Gnosis Safe proxy address to its underlying EOA via Polygon RPC
- **AI Profile** — generates a forensic behavioural profile of any tracked entity

---

## 🎯 Managing Your Watchlist

Wallets can be added directly from the **web dashboard** using the input form at the top of the Entity Watchlist panel. Enter the `0x...` proxy address and a human-readable label, then click **Add**.

Alternatively, you can add entries via the SQLite CLI:

```bash
sqlite3 polysint_core.db
```
```sql
INSERT INTO watch_list (address, label, added_at)
VALUES ('0xYourTargetProxyAddressHere', 'High-Volume Whale', datetime('now'));
.exit
```

The `watcher.py` daemon automatically picks up new entries on its next 5-minute cycle.

> **Address format:** The watchlist enforces strict 42-character `0x` addresses. Use the address found in the trader's Polymarket profile URL.

---

## 📂 Project Structure

| File | Description |
|------|-------------|
| `start.py` | Unified launcher — starts all daemons and runs the heartbeat loop |
| `api.py` | FastAPI endpoints for market data, AI analysis, and watchlist management |
| `harvest.py` | Data ingestion worker (Polymarket Gamma API, runs every 15 min) |
| `alerts.py` | Anomaly scanner — detects >10% shifts and broadcasts intelligence alerts |
| `watcher.py` | OSINT entity tracking worker (runs every 5 min) |
| `analyst.py` | LLM integration layer (market shift analysis & wallet profiling) |
| `clob.py` | Polymarket CLOB API client — fetches 24h price history and calculates shifts |
| `researcher.py` | Tavily web search integration for real-world news context (optional) |
| `notifier.py` | Webhook broadcaster (Discord & Telegram) |
| `utils.py` | Web3 / Polygon forensics (Gnosis Safe proxy unmasking) |
| `db.py` | SQLite WAL-mode connection manager & schema initialiser |
| `config.py` | Centralised environment variable loader |
| `logger.py` | Centralised logging to `analyzer.log` (WARNING level and above) |
| `static/index.html` | Web dashboard HTML |
| `static/app.js` | Web dashboard JavaScript |

---

## 🛠️ Troubleshooting

**Missing Data / No Alerts**  
Ensure `harvest.py` has completed at least one full run before starting `alerts.py`. For CLOB-based detection, `alerts.py` queries live price history directly — no minimum snapshot count is required. For the local snapshot fallback, a minimum of two snapshots per market is needed to calculate a shift.

**Web Research 400 Errors**  
`ENABLE_WEB_RESEARCH` defaults to `false`. Only set it to `true` in `.env` if you have a valid `TAVILY_API_KEY` configured. Web research can also be toggled per-request from the dashboard without changing the daemon setting.

**Cloudflare Blocking (403 or SSL errors)**  
Polymarket's Cloudflare protection may block the harvester. The script uses browser-mimicking headers, but a rotating proxy may be needed for heavy use. As a fallback, add `verify=False` to `session.get(...)` in `harvest.py`.

**CLOB SSL Warnings**  
Polymarket's CLOB endpoint uses a self-signed certificate. `clob.py` disables SSL verification and suppresses the urllib3 warning automatically — no action required.

**Rate Limiting (429)**  
`harvest.py` handles 429 responses automatically by sleeping for 10 seconds before retrying.

**Port Conflicts**  
The API server runs on port **9000** by default (not 8000). Adjust the `uvicorn` call in `start.py` if needed.

**Logs**  
Check `analyzer.log` in the root directory for WARNING, ERROR, and CRITICAL level events from all background workers.
