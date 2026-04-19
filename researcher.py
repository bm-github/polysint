import os
import requests
from logger import get_logger

log = get_logger("Researcher")

MAX_QUERY_LENGTH = 100

NEWS_DOMAINS = [
    "reuters.com",
    "apnews.com",
    "bloomberg.com",
    "bbc.com",
    "nytimes.com",
    "washingtonpost.com",
    "theguardian.com",
    "cnbc.com",
    "wsj.com",
    "ft.com",
    "politico.com",
    "thehill.com",
    "axios.com",
]

NICHE_DOMAINS = [
    "twitter.com",
    "x.com",
    "reddit.com",
    "substack.com",
    "discord.com",
]


class PolyResearcher:
    def __init__(self):
        self.api_key = os.getenv("TAVILY_API_KEY")

    def get_market_context(self, market_question):
        if not self.api_key:
            print("Warning: No TAVILY_API_KEY found. Skipping web search.")
            return "No search API key configured. Context unavailable."

        query_text = market_question
        if len(query_text) > MAX_QUERY_LENGTH:
            query_text = query_text[:MAX_QUERY_LENGTH].rsplit(' ', 1)[0]

        print(f"[RESEARCHER] Searching for: '{query_text}'...")

        all_results = []
        all_results.extend(self._tavily_search(query_text, NEWS_DOMAINS))
        all_results.extend(self._tavily_search(
            f"discussion opinion {query_text}", NICHE_DOMAINS, max_results=3
        ))

        if not all_results:
            return "No relevant news found."

        seen_urls = set()
        unique = []
        for r in all_results:
            url = r.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(r)

        context_parts = []
        for r in unique:
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

    def _tavily_search(self, query: str, domains: list, max_results: int = 5) -> list:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.api_key,
            "query": f"latest news: {query}",
            "search_depth": "basic",
            "include_domains": domains,
            "max_results": max_results,
        }

        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                print(f"[RESEARCHER] Found {len(results)} results from {', '.join(domains[:3])}")
                return results
            log.error(f"Tavily API error {resp.status_code} for query '{query}': {resp.text[:200]}")
            return []
        except Exception as e:
            log.error(f"Search failed: {e}")
            return []
