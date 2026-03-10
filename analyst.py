import os
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv
from researcher import PolyResearcher
from config import Config

load_dotenv()


def _derive_price_behaviour(price_history: list) -> dict:
    """
    Derives observable behavioural signals from a flat price list.
    These become first-class evidence for the LLM — it should never need to
    say "no data" about the price action itself, only about external news.

    Returns a dict of computed metrics with plain-English descriptions.
    """
    if not price_history or len(price_history) < 2:
        return {"summary": "Insufficient price history (fewer than 2 data points)."}

    try:
        prices = [float(p) for p in price_history]
    except (TypeError, ValueError):
        return {"summary": "Price data could not be parsed."}

    first = prices[0]
    last = prices[-1]
    high = max(prices)
    low = min(prices)
    total_shift = last - first
    total_range = high - low
    n = len(prices)

    # Find the single largest jump between consecutive points
    jumps = [(prices[i+1] - prices[i], i) for i in range(n - 1)]
    max_jump, max_jump_idx = max(jumps, key=lambda x: abs(x[0]))

    # Characterise where in the window the big move happened
    position_pct = round((max_jump_idx / max(n - 1, 1)) * 100)
    if position_pct < 25:
        jump_timing = "early in the window"
    elif position_pct < 75:
        jump_timing = "mid-window"
    else:
        jump_timing = "late in the window (recent)"

    # Is the move holding or reversing?
    # Compare last price to the price at peak/trough
    if total_shift > 0:
        reversal = round((high - last) * 100, 1)
        holding = reversal < 3.0
        reversal_note = f"Up {round(total_shift*100,1)}% overall; pulled back {reversal}% from peak — {'holding' if holding else 'showing reversal'}."
    elif total_shift < 0:
        reversal = round((last - low) * 100, 1)
        holding = reversal < 3.0
        reversal_note = f"Down {round(abs(total_shift)*100,1)}% overall; recovered {reversal}% from trough — {'holding' if holding else 'showing partial recovery'}."
    else:
        reversal_note = "No net movement over the window."

    # Was the move gradual or sudden?
    # Count how many steps account for 80% of the total absolute move
    total_abs = sum(abs(j[0]) for j in jumps)
    sorted_jumps = sorted(jumps, key=lambda x: abs(x[0]), reverse=True)
    cumulative = 0
    steps_for_80pct = 0
    for j, _ in sorted_jumps:
        cumulative += abs(j)
        steps_for_80pct += 1
        if total_abs > 0 and cumulative / total_abs >= 0.8:
            break

    if steps_for_80pct == 1:
        move_character = "single-step spike (one candle accounts for 80%+ of the move)"
    elif steps_for_80pct <= max(2, n // 6):
        move_character = f"sharp move concentrated in {steps_for_80pct} steps"
    else:
        move_character = f"gradual grind across {steps_for_80pct}+ steps"

    return {
        "data_points": n,
        "start_price": f"{round(first * 100, 1)}%",
        "end_price": f"{round(last * 100, 1)}%",
        "high": f"{round(high * 100, 1)}%",
        "low": f"{round(low * 100, 1)}%",
        "net_shift": f"{'+' if total_shift >= 0 else ''}{round(total_shift * 100, 1)}%",
        "largest_single_step": f"{'+' if max_jump >= 0 else ''}{round(max_jump * 100, 1)}% ({jump_timing})",
        "move_character": move_character,
        "trend_status": reversal_note,
    }


class PolyAnalyst:
    def __init__(self):
        self.client = OpenAI(
            base_url=os.getenv("LLM_API_BASE_URL"),
            api_key=os.getenv("LLM_API_KEY")
        )
        self.model = os.getenv("ANALYSIS_MODEL")
        self.researcher = PolyResearcher()

    def analyze_market_shift(self, market_question, price_history, volume, use_research: bool = None):
        """Explains WHY a market is moving, grounded first in price behaviour, then optionally in news."""
        if use_research is None:
            use_research = Config.ENABLE_WEB_RESEARCH

        # Always derive price behaviour — this is the primary evidence source
        behaviour = _derive_price_behaviour(price_history)

        if use_research:
            news_context = self.researcher.get_market_context(market_question)
        else:
            news_context = "Web research disabled. No external news context available."

        current_time = datetime.now(timezone.utc).strftime("%B %d, %Y - %H:%M:%S UTC")

        system_prompt = (
            "You are a Senior OSINT & Forensic Financial Analyst specialising in prediction markets. "
            f"CRITICAL: The current real-world date and time is {current_time}. "
            "Your analysis must be grounded in the evidence provided. "
            "The PRICE BEHAVIOUR section is primary evidence — it is derived directly from market data and is always available. "
            "The NEWS CONTEXT section is supplementary — it may be empty, in which case your analysis must still be substantive and grounded in the price behaviour alone. "
            "You must NEVER produce a finding of INSUFFICIENT DATA unless the price history itself has fewer than 2 data points. "
            "You must NEVER claim a move is unexplained simply because news is absent — price behaviour alone can support a classification. "
            "Do not invent events. Every factual claim must trace back to either the price behaviour metrics or a specific news item below."
        )

        prompt = f"""
MARKET QUESTION: "{market_question}"
TOTAL VOLUME: ${volume:,.0f}

━━━ PRIMARY EVIDENCE: PRICE BEHAVIOUR ━━━
{chr(10).join(f"  {k}: {v}" for k, v in behaviour.items())}

━━━ SUPPLEMENTARY EVIDENCE: NEWS CONTEXT ━━━
{news_context}

---
INSTRUCTIONS:

Work through the following steps IN ORDER.

STEP 1 - PRICE BEHAVIOUR ANALYSIS:
Using ONLY the price behaviour metrics above, describe what the market did.
Cover: the direction and magnitude of the move, whether it was sudden or gradual,
where in the time window it occurred, and whether it is holding or reversing.
This step must be completed even if news context is empty.

STEP 2 - NEWS CORRELATION (if news context is available):
List each news item that is directly relevant to this market.
For each relevant item, note its title, source URL, and published date.
If no news items are relevant, state: "No directly relevant news found."
If news context was disabled, state: "Web research was not run for this query."

STEP 3 - TIMING ANALYSIS:
Based on the move character (sudden vs gradual) and any dated news items:
- A sudden single-step spike with no news strongly suggests the information
  existed before it became public, or a large single trader acted on private conviction.
- A gradual grind is more consistent with slow public information diffusion.
- If dated news is available, state whether the market moved before or after it broke.
- If no news is available, base your timing assessment on the move character alone.

STEP 4 - CLASSIFICATION:
Classify as one of:
- REACTIONARY: A specific dated news item directly explains the shift and
  appeared before or concurrent with the market move.
- SUSPICIOUS: The move is sudden, large, and preceded available news — or the
  move character (single-step spike) is inconsistent with organic public information flow.
- ORGANIC: The move is gradual and consistent with slow public information
  diffusion, even without a specific news item.
- INSUFFICIENT DATA: Use ONLY if the price history has fewer than 2 data points.

STEP 5 - INTELLIGENCE BRIEF:
Write a 2-3 sentence brief. Every factual claim must be traceable to either
the price behaviour metrics (Step 1) or a specific news item (Step 2).
Do not hedge by saying the move is "unexplained" — explain what the data
shows even if the cause is uncertain.

STEP 6 - INSIDER SIGNAL SCORE (1-10):
Rate the probability of insider knowledge.
- Base the score on the move character: sudden spikes score higher than gradual grinds.
- Adjust up if the move preceded news; adjust down if news preceded the move.
- A score above 6 requires specific justification from Steps 1-3.
- Do NOT cap at 5 simply because news is absent — price behaviour is sufficient evidence.

---
OUTPUT FORMAT:

PRICE ACTION:
(Step 1 findings)

EVIDENCE:
(Step 2 findings, with source URLs if available — or explicit statement if none)

TIMING:
(Step 3 finding)

TYPE: (REACTIONARY / SUSPICIOUS / ORGANIC / INSUFFICIENT DATA)

ANALYSIS:
(Step 5 brief)

INSIDER SIGNAL: (1-10) — (one sentence justification referencing specific data points)
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        return response.choices[0].message.content

    def profile_wallet(self, wallet_address, real_owner, trades):
        """Profiles a specific trader based on behavior and unmasked ID."""

        current_time = datetime.now(timezone.utc).strftime("%B %d, %Y")
        system_prompt = (
            "You are a digital forensic profiler. "
            f"The current date is {current_time}. "
            "Base your analysis strictly on the trade data provided. "
            "Do not invent biographical details, assume identity, or speculate beyond what the trading patterns directly support. "
            "Where the data is insufficient to draw a conclusion, say so explicitly."
        )

        prompt = f"""
PROXY ADDRESS: {wallet_address}
REAL OWNER (EOA): {real_owner}
RECENT TRADES: {trades}

---
INSTRUCTIONS:

Work through the following steps IN ORDER.

STEP 1 - PATTERN ANALYSIS:
What observable patterns exist in the trade data above?
Consider: market niches traded, trade timing, position sizes, win/loss ratio if determinable.
If the trade list is too short or sparse to identify patterns, state this explicitly.

STEP 2 - ENTITY TYPE:
Based ONLY on the patterns from Step 1, suggest the most likely entity type from:
(Political Staffer, Domain Expert, Quantitative Bot, Retail Speculator, Market Maker, Whale, Unknown)
If Step 1 found insufficient data, classify as: Unknown — insufficient trade history.

STEP 3 - ALPHA LEVEL (1-10):
Rate their likely information edge.
A score above 6 requires a specific pattern from Step 1 to justify it.
If Step 1 found insufficient data, cap the score at 5.

---
OUTPUT FORMAT:

PATTERNS:
(Step 1 findings — or explicit statement that data is insufficient)

ENTITY TYPE: (from the list above)

ALPHA LEVEL: (1-10) — (one sentence justification referencing a specific pattern, or acknowledgement of data limits)
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        return response.choices[0].message.content
