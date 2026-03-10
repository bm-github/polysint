# 🕵️ PolySINT: Prediction Market OSINT Engine
**Version:** 1.0.0 (Core Backend Initialized)
**Type:** Headless Intelligence Platform / Microservice Architecture

## 1. Project Vision
PolySINT is an automated Open Source Intelligence (OSINT) platform designed to monitor Polymarket (via the Polygon blockchain). It identifies early warning signals, tracks insider trading behaviors, unmasks anonymous proxy wallets, and uses Large Language Models (LLMs) to provide cognitive forensic analysis of market anomalies.

## 2. System Architecture
The platform is built on a **Service-Oriented Architecture (SOA)** centered around a unified SQLite database using Write-Ahead Logging (WAL) for safe concurrent access. 

*   **The State (Memory):** SQLite (`polysint_core.db`)
*   **The Brain (Cognitive):** OpenAI-compatible LLM routing (via OpenRouter/Claude).
*   **The Interface (API):** FastAPI exposing data and AI endpoints.
*   **The Workers (Daemons):** Independent Python scripts running infinite loops.

## 3. Database Schema (`db.py`)
The system relies on three core tables:
1.  **`markets` (Static)**: 
    *   `id` (TEXT, PK): Polymarket Event ID.
    *   `question` (TEXT): The human-readable market question.
    *   `outcomes` (TEXT): JSON array of possible outcomes.
    *   `volume` (REAL): Lifetime volume at time of discovery.
    *   `created_at` (TEXT): ISO Timestamp of ingestion.
2.  **`snapshots` (Time-Series)**:
    *   `id` (INTEGER, PK, Auto): Internal ID.
    *   `market_id` (TEXT, FK): Links to `markets`.
    *   `timestamp` (DATETIME): ISO Timestamp of the snapshot.
    *   `prices` (TEXT): JSON array of probabilities at this exact moment.
    *   `volume` (REAL): Volume at this exact moment.
3.  **`watch_list` (Entities)**:
    *   `address` (TEXT, PK): The Polymarket Gnosis Safe proxy address.
    *   `label` (TEXT): OSINT tag (e.g., "AI Insider", "High-Volume Whale").
    *   `added_at` (DATETIME): Timestamp of tracking initiation.

## 4. Component Modules (The Codebase)
*   **`config.py`**: The single source of truth for environment variables (API URLs, RPC endpoints, LLM keys).
*   **`logger.py`**: Standardized logging utility writing to `analyzer.log` (WARNING level and above).
*   **`db.py`**: SQLite connection manager ensuring `PRAGMA journal_mode=WAL;` is set to prevent locking across workers.
*   **`utils.py`**: Blockchain forensics. Uses `web3.py` and Infura RPC to call `getOwners()` on Gnosis Safe contracts, bypassing Polymarket anonymity.
*   **`analyst.py`**: The LLM ingestion layer. Feeds market deltas and wallet transaction history to Claude/GPT to generate human-readable intelligence briefs.
*   **`api.py`**: The FastAPI application serving as the "One Interface" (`http://localhost:9000/docs`).

## 5. Background Workers (Daemons)
*   **`harvest.py`**: The Data Ingester. Runs every 15 minutes. Scrapes the Gamma API, registers new markets, and appends a new row to `snapshots` for every active market.
*   **`alerts.py`**: The Anomaly Detector. Runs every 5 minutes. Compares the two most recent snapshots in the DB. If a probability shifts by >5% (0.05), it triggers an alert.
*   **`watcher.py`**: The Whale Tracker. Runs every 5 minutes. Queries the `watch_list`, fetches recent trades via the Data API, and logs new activity.

---

## 6. Development Roadmap (Next Specs)

To continue with Spec-Driven Development, choose one of the following "Phases" for your next coding session. 

### Phase 1: The Notification Layer
*   **Spec Goal:** `alerts.py` and `watcher.py` currently print to the console. They need to send actionable OSINT to a device.
*   **Implementation Plan:** 
    *   Create `notifier.py` with Discord/Telegram webhook support.
    *   When `alerts.py` detects a >10% shift, it automatically calls `analyst.py` to get an "Intelligence Brief" and sends the formatted brief + the price shift to the webhook.

### Phase 2: The Web Dashboard (Frontend)
*   **Spec Goal:** Build a visual UI to consume `api.py` without using the FastAPI `/docs` page.
*   **Implementation Plan:**
    *   Create a `static/` folder with `index.html` and `app.js`.
    *   Add a Dashboard showing: "Top Movers (Last 24h)", "Recent Whale Trades", and a search bar for specific markets.
    *   Include an "Analyze" button next to markets that hits the `/markets/{id}/ai-analysis` endpoint and displays the LLM response in a modal.

### Phase 3: Automated Entity Resolution
*   **Spec Goal:** Connect the harvester to the unmasking utility to build a map of linked wallets automatically.
*   **Implementation Plan:**
    *   Create a new DB table: `linked_entities (human_eoa, proxy_wallet, first_seen)`.
    *   Upgrade `watcher.py` to automatically pass new whale proxy addresses through `utils.unmask_proxy` and save the real EOA to the database.
    *   Trigger an alert if two *different* proxy wallets in the `watch_list` resolve to the *same* Real EOA.

### Phase 4: Narrative Correlation (Social OSINT)
*   **Spec Goal:** Cross-reference Polymarket financial odds with Social Media sentiment.
*   **Implementation Plan:**
    *   Integrate the social media OSINT tool you mentioned previously.
    *   Feed the LLM two data streams: X/Twitter trending headlines vs. Polymarket odds.
    *   Prompt the LLM to output a "Narrative Discrepancy Score" (e.g., "Media is panicking, but smart money is not moving").

---

### How to use this document moving forward:
Whenever you open a new chat window or start a new coding day, paste the message:
> *"Here is the current SPEC for my PolySINT project. [Paste Document]. Today, I want to implement Phase [X]. Let's write the code for it, ensuring we strictly adhere to `config.py`, `db.py`, and `logger.py` standards."*