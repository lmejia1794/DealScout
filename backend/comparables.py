"""
comparables.py — Phase 3 AI calls for DealScout.

Endpoint served via main.py:
  POST /api/comparables  → SSE stream → ComparablesResponse
"""

import logging
import re

from search import _get_client, format_results, _run_search, _extract_keywords
from research import (
    _call_json,
    _web_llm_enabled,
    WEB_CTX_MAX,
    TODAY,
)

_CITATION_RE = re.compile(r'\s*\[SRC:[^\]]*\]')


def _clean_tx(tx: dict) -> dict:
    """Strip [SRC: ...] markers from all string fields in a transaction."""
    return {
        k: _CITATION_RE.sub('', str(v)).strip() if isinstance(v, str) else v
        for k, v in tx.items()
    }

logger = logging.getLogger(__name__)


def generate_comparables(thesis: str, sector_brief: str, log_fn=None) -> list:
    """
    Generate 6–10 comparable M&A transactions relevant to the thesis.
    Returns a list of dicts matching ComparableTransaction shape.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    _log("=== Comparable Transactions ===")

    # Step 1 — Tavily searches
    if _web_llm_enabled():
        _log("WEB_LLM mode — skipping Tavily searches for comparables")
        web_context = ""
    else:
        _log("Running Tavily searches for M&A comparables...")
        sector, _ = _extract_keywords(thesis)
        client = _get_client()
        queries = [
            f"{sector} software M&A acquisition 2023 2024 2025",
            f"{sector} SaaS buyout private equity Europe",
            f"{sector} company acquired deal",
        ]
        blocks = [format_results(_run_search(client, q), q) for q in queries]
        web_context = "\n\n".join(blocks)
        _log(f"Searches complete — {len(web_context.splitlines())} lines of context, {len(web_context)} chars")
        if WEB_CTX_MAX > 0 and len(web_context) > WEB_CTX_MAX:
            web_context = web_context[:WEB_CTX_MAX]
            _log(f"Web context truncated to {WEB_CTX_MAX} chars")

    web_section = (
        "Use your web search capability to find real M&A transactions for this sector."
        if _web_llm_enabled()
        else f"Web search results:\n{web_context}"
    )

    # Step 2 — LLM call
    _log("Generating comparable transactions...")
    prompt = f"""You are a senior private equity analyst researching M&A precedent transactions.

Investment thesis: {thesis}

Sector context:
{sector_brief[:800]}

{web_section}

Today's date: {TODAY}

Identify 6–10 real, specific M&A transactions that are relevant to this sector and investment thesis.

Rules:
- Prefer European targets but include relevant global deals if they illustrate pricing
- Only include completed transactions — not rumoured or pending
- If EV or multiple is undisclosed, return null — do not fabricate numbers
- Do not include transactions announced after {TODAY}

Return ONLY a raw JSON array where each object has exactly these keys:
- target (string — acquired company name)
- acquirer (string — acquiring company or fund name)
- year (integer or null)
- deal_type (string — one of: "PE Buyout", "Strategic Acquisition", "Growth Investment")
- reported_ev (string e.g. "€120M" or null if undisclosed; append [SRC: url] if found in search results)
- reported_multiple (string e.g. "6× ARR" or null if undisclosed; append [SRC: url] if found in search results)
- target_description (string — 1 sentence on what the target does)
- relevance (string — 1 sentence on why it's relevant to this thesis)

For reported_ev and reported_multiple: only append [SRC: url] when you found those specific figures in the search results. Do not invent URLs."""

    transactions = _call_json(prompt, log_fn=log_fn)
    # Strip any [SRC: ...] citation markers from display fields
    transactions = [_clean_tx(tx) for tx in transactions if isinstance(tx, dict)]
    _log(f"Comparables complete ({len(transactions)} transactions)")
    return transactions
