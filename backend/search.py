import os
import re
from typing import Optional
from tavily import TavilyClient

_client: Optional[TavilyClient] = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        api_key = os.getenv("TAVILY_API_KEY", "")
        _client = TavilyClient(api_key=api_key)
    return _client


def _extract_keywords(thesis: str) -> tuple[str, str]:
    """
    Naively extract a sector keyword and geography keyword from the thesis.
    Returns (sector, geography).
    """
    geo_tokens = ["dach", "europe", "uk", "germany", "france", "nordics", "benelux",
                  "spain", "italy", "poland", "netherlands", "austria", "switzerland",
                  "scandinavia", "iberia", "cee"]
    geo = "Europe"
    for token in geo_tokens:
        if token.lower() in thesis.lower():
            geo = token.upper() if len(token) <= 4 else token.title()
            break

    # Remove common filler words and geo tokens, take first meaningful noun phrase
    stopwords = {"software", "saas", "companies", "company", "targeting", "with", "in",
                 "for", "and", "the", "a", "an", "of", "at", "to", "tech", "technology",
                 "arr", "revenue", "b2b", "smb", "mid-market", "enterprise", "size",
                 "mid", "large", "small"} | set(geo_tokens)
    words = re.findall(r"[a-zA-Z\-]+", thesis)
    sector_words = [w for w in words if w.lower() not in stopwords and len(w) > 3]
    sector = " ".join(sector_words[:3]) if sector_words else "B2B software"

    return sector, geo


def _run_search(client: TavilyClient, query: str) -> list[dict]:
    try:
        result = client.search(query, search_depth="advanced", max_results=5)
        return result.get("results", [])
    except Exception as e:
        print(f"[search] Tavily query failed: '{query}' — {e}")
        return []


def format_results(results: list[dict], query: str, max_chars_per_result: int = 300) -> str:
    if not results:
        return f'[Search: "{query}"]\n(no results)\n'
    lines = [f'[Search: "{query}"]']
    for r in results:
        title = r.get("title", "Untitled")
        content = r.get("content", "")[:max_chars_per_result].replace("\n", " ")
        url = r.get("url", "")
        lines.append(f"- {title}: {content} ({url})")
    return "\n".join(lines)


def search_for_sector_brief(thesis: str) -> str:
    sector, geo = _extract_keywords(thesis)
    client = _get_client()
    queries = [
        f"{sector} software market size {geo} 2024 2025",
        f"{sector} SaaS private equity M&A acquisitions 2023 2024 2025",
        f"{sector} software companies {geo} market share vendors",
        f"{sector} industry trends growth drivers 2025 2026",
        f"PE buyout {sector} software {geo} EV multiple deal",
        f"{sector} software acquisition strategic buyer {geo} 2023 2024 2025",
        f"{sector} SaaS exit multiple EV ARR comparable transaction",
    ]
    blocks = [format_results(_run_search(client, q), q, max_chars_per_result=500) for q in queries]
    return "\n\n".join(blocks)


def search_for_conferences(thesis: str) -> str:
    sector, _ = _extract_keywords(thesis)
    client = _get_client()
    queries = [
        f"{sector} conference 2026",
        f"{sector} industry event Europe 2026",
        f"b2b tech {sector} summit 2026",
    ]
    blocks = [format_results(_run_search(client, q), q) for q in queries]
    return "\n\n".join(blocks)


def search_for_companies(thesis: str) -> str:
    sector, geo = _extract_keywords(thesis)
    client = _get_client()
    queries = [
        f"{sector} software companies Europe",
        f"top {sector} SaaS vendors {geo}",
        f"{sector} startup Europe funding 2024 2025",
    ]
    blocks = [format_results(_run_search(client, q), q) for q in queries]
    return "\n\n".join(blocks)
