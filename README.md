# PolySINT: Prediction Market OSINT Engine

**PolySINT** is an automated Open Source Intelligence (OSINT) platform designed to monitor Polymarket via the Polygon blockchain. It identifies early warning signals, tracks insider trading behaviours, unmasks anonymous proxy wallets through recursive on-chain resolution, performs orderbook depth analysis, detects sybil clusters, and uses Large Language Models (LLMs) to synthesize forensic intelligence briefs from multi-source data.

## Features

### Market Intelligence
- **Automated Harvester** — Paginates Polymarket's Gamma API every 15 minutes, ingesting active markets with volume, outcomes, and CLOB token IDs. Backfills missing token IDs on startup.
- **CLOB Price History** — Fetches live 24-hour price history from `clob.polymarket.com` with 60-second caching. Local snapshot fallback if CLOB is unavailable.
- **Orderbook Depth Analysis** — Real-time bid/ask liquidity, spread, imbalance ratio, wall detection, and directional pressure signals (BUYING_PRESSURE / SELLING_PRESSURE / NEUTRAL).
- **Anomaly Detection** — Monitors markets for probability shifts exceeding 10% over 24 hours. Filters by minimum volume ($5K) and suppresses near-resolution noise (>80%/<20%). Broadcasts alerts to all channels.

### Entity Intelligence
- **Trade Sizing** — Every trade classified as RETAIL (<$5K), WHALE ($5K-$50K), or MEGA-WHALE (>$50K) with tiered alert formatting.
- **Persisted Trade Deduplication** — Seen trades stored in SQLite. No duplicate alerts after restart.
- **Trade History Logging** — All entity trades persisted to `entity_trades` with size, side, market, price, and timestamp.
- **Auto-Unmasking** — Watched wallets are automatically resolved from proxy to EOA on first detection.
- **Recursive Proxy Resolution** — Unmasks Gnosis Safe proxies up to 5 levels deep, detects multi-sig vs single-sig (`getThreshold()`), and enumerates delegate modules (`getModules()`).
- **Sybil Cluster Detection** — Alerts when multiple proxy wallets in the watchlist resolve to the same real EOA.
- **Leading Trade Detection** — Correlates entity trades with subsequent market moves. Alerts if a market shifts >=5% within 60 minutes of a watched entity's trade.
- **Entity Profiling** — LLM-generated behavioural profiles classifying traders as Political Staffer, Domain Expert, Quant Bot, Retail Speculator, Market Maker, or Whale, with an Alpha Level (1-10).

### AI Analysis
- **Intelligence Briefs** — LLM evaluates *why* a market is moving using a structured 6-step prompt: price behaviour analysis, news correlation, timing analysis, classification (REACTIONARY / SUSPICIOUS / ORGANIC), intelligence brief, and Insider Signal Score (1-10).
- **Price Behaviour Derivation** — Quantitative metrics fed to the LLM: net shift, largest single step, move character (spike vs grind), trend status (holding vs reversing).
- **Web Research** — Optional Tavily integration searching 18+ sources (Reuters, Bloomberg, Politico, Axios, FT, BBC, NYT, WSJ, CNBC, The Guardian, The Hill, plus Twitter/X, Reddit, Substack). Two-pass: hard news + social discussion.

### Infrastructure
- **Crash Recovery** — `start.py` auto-restarts crashed workers with configurable delay and notifies on crash/restore.
- **Rate Limiting** — IP-based rate limiting on all API endpoints (default 60 requests/minute, configurable).
- **Optional API Authentication** — Set `POLYSINT_API_KEY` to require `X-API-Key` header or `?api_key=` query param on all non-static endpoints.
- **Security Headers** — CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy applied via middleware.
- **SQLite with WAL + Retry** — Write-Ahead Logging with exponential backoff on lock contention (5 retries).
- **Indexed Database** — 8 indexes on hot query paths (snapshots by market+timestamp, entity trades by proxy, linked entities by EOA, etc.).
- **Notification Layer** — Discord and/or Telegram webhooks with periodic health heartbeat every 6 hours.
- **Web Dashboard** — Dark-mode UI with market table, anomaly highlights, watchlist manager, and AI analysis modals.

---

## Getting Started

### 1. Prerequisites
Ensure you have **Python 3.9+** installed. You will also need:
- An API key for your preferred LLM (OpenAI, or any OpenAI-compatible provider such as OpenRouter for Claude)
- A **Tavily API key** for real-world news context — optional ([tavily.com](https://tavily.com))
- Optionally, webhooks for Discord and/or Telegram notifications

### 2. Installation
Clone the repository and install dependencies:

```bash
git clone https://github.com/bm-github/polysint.git
cd polysint

python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file in the root directory:

```env
# Blockchain
POLYGON_RPC_URL="https://polygon-rpc.com"

# LLM / AI Analyst
LLM_API_KEY="your_llm_api_key_here"
LLM_API_BASE_URL="https://api.openai.com/v1"
ANALYSIS_MODEL="gpt-4o"

# Web Research via Tavily (Optional)
# TAVILY_API_KEY="your_tavily_api_key_here"
# ENABLE_WEB_RESEARCH=false

# Notification Webhooks (Optional)
# DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
# TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
# TELEGRAM_CHAT_ID="your_telegram_chat_id"

# API Authentication (Optional — leave blank to disable)
# POLYSINT_API_KEY="your_secret_key"

# Rate Limiting (Default: 60 requests/minute per IP)
# RATE_LIMIT_PER_MINUTE=60

# Entity Tracking Thresholds
# WHALE_THRESHOLD=5000
# MEGA_THRESHOLD=50000
# WATCHER_LEAD_WINDOW_MINUTES=60
```

> **Web Research:** `TAVILY_API_KEY` is optional. When `ENABLE_WEB_RESEARCH=true`, background daemons fetch news to help classify market moves. Can also be toggled per-request from the dashboard.

> **API Auth:** If `POLYSINT_API_KEY` is set, all API endpoints (except static files and the dashboard) require authentication via `X-API-Key` header or `?api_key=` query parameter.

---

## Running the Engine

### Recommended: One-Command Launch

```bash
python start.py
```

This will:
1. Launch the **FastAPI server** on port **9000**
2. Launch the **Data Harvester** (with CLOB token ID backfill)
3. Launch the **Anomaly Detector**
4. Launch the **Whale Watcher** (with auto-unmask and sybil detection)
5. Send a boot notification to Discord/Telegram
6. **Auto-restart** any worker that crashes
7. Send a health check every **6 hours**

Press `Ctrl+C` to safely shut down all processes (with 10-second graceful timeout, then force-kill).

---

### Alternative: Manual Launch

#### Step 1: Start the API
```bash
uvicorn api:app --port 9000 --reload
```
API docs at [http://localhost:9000/docs](http://localhost:9000/docs). Dashboard at [http://localhost:9000](http://localhost:9000).

#### Step 2: Start the Data Harvester
```bash
python harvest.py
```
> Wait for at least one full run before starting the Anomaly Detector.

#### Step 3: Start the Anomaly Detector
```bash
python alerts.py
```

#### Step 4: Start the Whale Watcher
```bash
python watcher.py
```

---

## API Endpoints

### Markets
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/markets` | Search/filter markets by keyword, volume range. Returns enriched data with 24h shift and current price. |
| GET | `/markets/{id}/ai-analysis` | Full LLM intelligence brief. Params: `?research=true`, `?force=true`. Cached 1 hour. |
| GET | `/markets/{id}/orderbook` | Orderbook depth analysis — bid/ask liquidity, spread, imbalance, walls, pressure signal. |

### Entities
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/watchlist` | List all watched entities. |
| POST | `/watchlist` | Add entity. Body: `{"address": "0x...", "label": "Name"}`. |
| DELETE | `/watchlist/{address}` | Remove entity. |
| GET | `/wallets/{address}/unmask` | Resolve proxy to EOA (single-level). |
| GET | `/wallets/{address}/unmask/full` | Full recursive unmask — ownership chain, threshold, modules, all owners. |
| GET | `/wallets/{address}/profile` | LLM-generated behavioural profile. |
| GET | `/wallets/{address}/trades` | Persisted trade history for entity. |
| GET | `/wallets/{address}/alerts` | Historical alerts (sybil clusters, leading trades) for entity. |
| GET | `/wallets/{address}/linked` | All proxy wallets linked to the same EOA. |

---

## Web Dashboard

Open [http://localhost:9000](http://localhost:9000) when the API is running.

### Markets Panel
- **Top Markets by Volume** — sorted by 24h volatility, anomalies (>=10%) in red with animated badge, warnings (>=5%) in amber
- **Real-time Odds** — current YES probability displayed under each market
- **24h Shift** — directional price movement (up/down) from CLOB history
- **AI Analyze** — on-demand LLM intelligence brief with 1-hour caching, force-refresh option, and web research toggle
- **Orderbook** — opens depth analysis modal showing bid/ask liquidity bars, spread, imbalance ratio, wall counts, and directional pressure signal (BUYING_PRESSURE / SELLING_PRESSURE / NEUTRAL)
- **Auto-Refresh** — 5-minute cycle with live countdown
- **Volume Filter** — min/max volume filters in the navbar, applied on search
- **Web Research Toggle** — per-request Tavily toggle persisted in localStorage

### Entity Watchlist Panel
- **Add/Remove** — add wallets by 0x address + label, delete with confirmation
- **Expandable Detail** — click any entity label to open a tabbed detail panel:
  - **Trades** — last 20 persisted trades with side (BUY/SELL), market, size, and date
  - **Alerts** — sybil cluster and leading trade alert history with type badges
  - **Linked** — all proxy wallets sharing the same EOA (sybil cluster map)
- **Unmask** — calls the full recursive unmask endpoint, rendering the complete ownership chain (Proxy -> Layer N -> EOA), wallet type (GNOSIS_SAFE SINGLE-SIG / MULTI-SIG), and threshold
- **AI Profile** — LLM-generated forensic behavioural profile with unmasked EOA displayed

### Security
- **XSS-safe rendering** — all dynamic content (market questions, entity labels, LLM output) is HTML-escaped before insertion
- **API key support** — if auth is enabled (`POLYSINT_API_KEY` in `.env`), the dashboard prompts for a key on first 401 and stores it in localStorage for all subsequent requests
- **Modal dismiss** — click outside modal or press Escape to close

---

## Managing Your Watchlist

Add wallets from the **dashboard** or via SQLite:

```bash
sqlite3 polysint_core.db
```
```sql
INSERT INTO watch_list (address, label, added_at)
VALUES ('0xYourTargetProxyAddressHere', 'High-Volume Whale', datetime('now'));
```

The watcher daemon picks up new entries on its next 5-minute cycle. Each new wallet is automatically unmasked and checked against the linked entity map for sybil clusters.

> **Address format:** 42-character `0x` address. Use the address from the trader's Polymarket profile URL.

---

## Project Structure

| File | Description |
|------|-------------|
| `start.py` | Unified launcher with auto-restart and heartbeat |
| `api.py` | FastAPI endpoints, rate limiting, auth middleware, security headers |
| `harvest.py` | Gamma API harvester with pagination, snapshot writing, CLOB token ID backfill |
| `alerts.py` | Anomaly scanner — >=10% shift detection with volume/near-resolution filtering |
| `watcher.py` | Entity tracker — trade sizing, persisted dedup, auto-unmask, sybil detection, leading trade analysis |
| `analyst.py` | LLM integration — market analysis, price behaviour derivation, entity profiling |
| `clob.py` | CLOB API client — price history, shift calculation, orderbook depth analysis |
| `researcher.py` | Tavily integration — 18+ news + social sources, two-pass search |
| `notifier.py` | Webhook broadcaster (Discord & Telegram) |
| `utils.py` | Web3 forensics — recursive proxy unmasking, multi-sig detection, module enumeration |
| `db.py` | SQLite WAL manager, schema migrations, indexes, retry-with-backoff |
| `config.py` | Centralised environment config (all settings via `.env`) |
| `logger.py` | Centralised logging to `analyzer.log` |
| `static/index.html` | Dashboard HTML |
| `static/app.js` | Dashboard JavaScript |

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `markets` | Active Polymarket markets with CLOB token IDs |
| `snapshots` | Time-series price snapshots (fallback for CLOB) |
| `watch_list` | Tracked entity proxy addresses with labels |
| `analyses` | Cached LLM intelligence briefs (1-hour TTL) |
| `seen_trades` | Persisted trade deduplication (survives restarts) |
| `linked_entities` | EOA-to-proxy mappings from auto-unmasking |
| `entity_trades` | Full trade history for all watched entities |
| `entity_alerts` | Historical alerts (sybil clusters, leading trades) |

---

## Troubleshooting

**Missing Data / No Alerts**
Ensure `harvest.py` has completed at least one full run before starting `alerts.py`. CLOB-based detection queries live price history directly. Snapshot fallback requires >=2 snapshots per market.

**Web Research 400 Errors**
`ENABLE_WEB_RESEARCH` defaults to `false`. Only set to `true` with a valid `TAVILY_API_KEY`. Can be toggled per-request from the dashboard.

**Cloudflare Blocking (403)**
The harvester uses browser-mimicking headers with automatic retry. A rotating proxy may be needed for heavy use.

**CLOB SSL Warnings**
`clob.py` disables SSL verification and suppresses urllib3 warnings automatically.

**Rate Limiting (429)**
The harvester retries 429 responses with exponential backoff. The API has its own rate limiter (default 60/min per IP, configurable via `RATE_LIMIT_PER_MINUTE`).

**Worker Crashes**
`start.py` auto-restarts crashed workers after a 10-second delay and sends crash/restore notifications via webhooks.

**Port Conflicts**
API runs on port **9000** by default. Adjust the `uvicorn` call in `start.py` if needed.

**Logs**
Check `analyzer.log` for WARNING, ERROR, and CRITICAL events from all workers.
