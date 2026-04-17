"""
scraper.py — AI-picked source scraping for DealScout.

Pre-step before the main pipeline:
  1. pick_sources()      — ask Gemini to identify authoritative URLs for the thesis
  2. scrape_sources()    — fetch + extract readable text from those URLs in parallel
  3. get_source_context() — convenience wrapper, returns combined text
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from bs4 import BeautifulSoup

from research import _call_llm, _strip_json_fences, WEB_CTX_MAX, TODAY

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Characters of extracted text to keep per source
_PER_SOURCE_CHARS = 2000


def pick_sources(thesis: str) -> list:
    """
    Ask the LLM to suggest 4–6 authoritative, publicly accessible URLs
    relevant to the investment thesis.  Returns [] on any failure.
    """
    prompt = f"""You are a research librarian helping a private equity analyst.

Investment thesis: {thesis}

Today's date: {TODAY}

Identify 4–6 authoritative, publicly accessible web pages that would give the most useful
context about this sector and the types of companies being sought.

Rules:
- Return ONLY a raw JSON array of URL strings — no other text
- URLs must be freely accessible without login or paywall
- Good source types:
  - Software review aggregators: g2.com/categories/..., capterra.com/...-software, getapp.com
  - Industry association websites
  - Trade publications with free content
  - Relevant Wikipedia category or comparison pages
  - Sector-specific European tech news (sifted.eu, eu-startups.com)
- Avoid: PitchBook, Dealroom, Statista premium, Bloomberg, LinkedIn, Crunchbase (require login)
- Prefer sources with content updated recently (2024–2025)

Return ONLY the JSON array, e.g.: ["https://...", "https://..."]"""

    try:
        raw = _call_llm(prompt, 500)
        urls = json.loads(_strip_json_fences(raw))
        if isinstance(urls, list):
            return [u for u in urls if isinstance(u, str) and u.startswith("http")]
        return []
    except Exception as e:
        logger.warning("pick_sources failed: %s", e)
        return []


def _scrape_one(url: str) -> tuple:
    """
    Fetch a single URL and return (url, text, error_msg).
    text is empty string on failure, error_msg is None on success.
    """
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _BROWSER_UA})
            resp.raise_for_status()

        # Cap raw HTML before parsing to avoid large pages filling memory
        raw_html = resp.text[:300_000]
        soup = BeautifulSoup(raw_html, "lxml")

        # Remove noise tags
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Find main content area
        content = (
            soup.find("article")
            or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find(class_="content")
            or soup.find(id="content")
            or soup.body
        )

        if not content:
            return url, "", "no content found"

        text = content.get_text(separator=" ", strip=True)
        # Collapse whitespace
        text = re.sub(r"\s{2,}", " ", text)
        text = text[:_PER_SOURCE_CHARS]
        return url, text, None

    except httpx.TimeoutException:
        return url, "", "timeout"
    except httpx.HTTPStatusError as e:
        return url, "", f"HTTP {e.response.status_code}"
    except Exception as e:
        return url, "", str(e)


def scrape_sources(urls: list, log_fn=None) -> str:
    """
    Scrape each URL in parallel (ThreadPoolExecutor).
    Returns combined text formatted as [Source: url]\\ntext\\n...
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    if not urls:
        return ""

    if WEB_CTX_MAX > 0 and WEB_CTX_MAX < 2000:
        _log(f"WARNING: WEB_CTX_MAX={WEB_CTX_MAX} is low — scraped source content may be heavily truncated. Consider setting WEB_CTX_MAX=4000.")

    _log(f"Scraping {len(urls)} sources in parallel...")

    blocks = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_scrape_one, url): url for url in urls}
        for future in as_completed(futures):
            url, text, err = future.result()
            if err:
                _log(f"Failed: {url} ({err}) — skipping")
            else:
                _log(f"Scraped: {url} ({len(text)} chars)")
                blocks.append(f"[Source: {url}]\n{text}")

    combined = "\n\n".join(blocks)
    _log(f"Source scraping complete — {len(combined)} chars total context")
    return combined


def get_source_context(thesis: str, log_fn=None) -> str:
    """
    Convenience wrapper: pick sources then scrape them.
    Returns combined text, or empty string on any failure.
    This step is best-effort and must never raise.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    try:
        _log("Picking authoritative sources for thesis...")
        urls = pick_sources(thesis)
        if not urls:
            _log("No sources selected — skipping scraping")
            return ""
        _log(f"Selected {len(urls)} sources: {', '.join(urls)}")
        return scrape_sources(urls, log_fn=log_fn)
    except Exception as e:
        _log(f"Source discovery failed ({e}) — continuing without scraped context")
        return ""
