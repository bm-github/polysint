import os
import requests
from dotenv import load_dotenv
from logger import get_logger

load_dotenv()
log = get_logger("Researcher")

MAX_QUERY_LENGTH = 100  # Tavily 400s on overly long queries

class PolyResearcher:
    def __init__(self):
        self.api_key = os.getenv("TAVILY_API_KEY")

    def get_market_context(self, market_question):
        """Searches for real-world events related to the market question."""
        if not self.api_key:
            print("⚠️ [RESEARCHER] No TAVILY_API_KEY found in .env! Skipping web search.")
            return "No search API key configured. Context unavailable."

        # Truncate long questions to avoid Tavily 400 errors
        query_text = market_question
        if len(query_text) > MAX_QUERY_LENGTH:
            query_text = query_text[:MAX_QUERY_LENGTH].rsplit(' ', 1)[0]  # trim at word boundary

        print(f"🔎[RESEARCHER] Scouring the web for: '{query_text}'...")

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.api_key,
            "query": f"latest news: {query_text}",
            "search_depth": "basic",  # valid values: "ultra-fast", "fast", "basic", "advanced"
            "include_domains": ["reuters.com", "apnews.com", "bloomberg.com", "twitter.com"],
            "max_results": 5
        }

        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                print(f"✅ [RESEARCHER] Found {len(results)} relevant news articles.")

                if not results:
                    return "No relevant news found."

                context_parts = []
                for r in results:
                    title = r.get('title', 'Untitled')
                    snippet = r.get('content', '')[:300]
                    source_url = r.get('url', 'URL unavailable')
                    published = r.get('published_date', 'Date unknown')
                    context_parts.append(
                        f"- TITLE: {title}\n"
                        f"  DATE: {published}\n"
                        f"  SOURCE: {source_url}\n"
                        f"  SNIPPET: {snippet}..."
                    )

                return "\n\n".join(context_parts)

            log.error(f"Tavily API error {resp.status_code} for query '{query_text}': {resp.text[:200]}")
            print(f"❌ [RESEARCHER] API Error: {resp.status_code}")
            return "Search failed (API Error)."
        except Exception as e:
            log.error(f"Search failed: {e}")
            print("❌ [RESEARCHER] Network Error.")
            return "Search failed (Network Error)."
