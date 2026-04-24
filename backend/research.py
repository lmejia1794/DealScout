"""
research.py — all AI calls for DealScout Phase 1.

Sequential pipeline:
  1. sector_brief   → markdown string
  2. conferences    → list[dict]
  3. companies      → list[dict]

Each step receives prior outputs as context so later steps are grounded.
Adding Phase 2 steps means appending new functions in the same pattern —
no refactoring of existing steps required.
"""

import json
import logging
import math
import os
import re
import threading
import time
from datetime import date

# Thread-local LLM meta — records the last backend+model used on each thread.
# Safe because research, verification, and citation-repair each run on their own thread.
_thread_llm_meta = threading.local()

def _get_last_llm_meta() -> dict:
    return {
        "backend": getattr(_thread_llm_meta, "backend", None),
        "model":   getattr(_thread_llm_meta, "model",   None),
        "search":  getattr(_thread_llm_meta, "search",  False),
    }

from google import genai
from google.genai import types as genai_types
import httpx
from openai import OpenAI

from search import search_for_sector_brief, search_for_conferences, search_for_companies, _extract_keywords

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a structured data assistant. "
    "When asked to return JSON, return ONLY valid JSON with no markdown fences, "
    "no preamble, and no explanation. "
    "When asked to return markdown, return only markdown."
)
TEMPERATURE = 0.2
JSON_TOKENS = 12000
BRIEF_TOKENS = 6000

# Maximum characters of Tavily web context to inject per prompt.
# Set WEB_CTX_MAX=0 to disable the cap entirely (useful when the Ollama server
# has a large context window configured).  Any positive value truncates to that
# many chars.  Default 1200 is safe for a 2048-token context window.
WEB_CTX_MAX = int(os.getenv("WEB_CTX_MAX", "8000"))

TODAY = date.today().strftime("%B %Y")  # e.g. "April 2026"

# Whether to inject citation prompts at generation time (free — no Tavily)
_CITATIONS_ENV = os.getenv("VERIFICATION_CITATIONS_ENABLED", "true").lower() in ("1", "true", "yes")

CITATION_PROMPT_BLOCK = """
CITATIONS REQUIREMENT — mandatory, not optional:
Every specific factual claim must have an inline [SRC: ...] marker immediately after it.
This includes: every number, percentage, market size, growth rate, company name, founding year,
ownership detail, deal value, or statistic.

Citation format (pick exactly one per claim):
- Data from a URL in the search results above: [SRC: https://exact-url-from-results]
  The URL for each search result is shown in parentheses at the end of each result line —
  copy that exact URL. Do not paraphrase or shorten it.
- Training knowledge with no searchable source: [SRC: training_knowledge]
- Estimate or model inference: [SRC: estimated]
- Derived from another cited claim: [SRC: derived]

Do NOT use [SRC: model_inference].

Example:
"The DACH WFM market is valued at €2.1B [SRC: https://example.com/report-2025], growing at
8-12% annually [SRC: training_knowledge], with roughly 500 vendors [SRC: estimated]."

Cite every claim. Uncited claims are treated as unverified.
"""

# Separate block for WEB_LLM mode — Gemini has built-in search, not injected context
WEB_LLM_CITATION_BLOCK = """
CITATIONS REQUIREMENT — mandatory, not optional:
You have web search enabled and are retrieving live content from real URLs.
For EVERY factual claim append an inline [SRC: ...] marker immediately after the claim,
using the actual URL of the page you found that data on.

Citation format (pick exactly one per claim):
- URL you actually retrieved during this search: [SRC: https://full-url-you-accessed]
- Genuine training knowledge (could not find via search): [SRC: training_knowledge]
- Estimate or inference: [SRC: estimated]
- Derived from another cited value: [SRC: derived]

Do NOT write [SRC: training_knowledge] for data you found by searching — use the real URL.
Do NOT use [SRC: model_inference].

Example:
"The European logistics software market is valued at €8.2B [SRC: https://example.com/2025-report]
growing at 12% annually [SRC: https://example.com/2025-report], with over 400 vendors
[SRC: estimated]."

Every number and named statistic must be cited. Uncited claims are treated as unverified.
"""

# Regex patterns for size criteria in the thesis
_SIZE_RE = re.compile(
    r'(?P<ccy>[€$£])\s*(?P<lo>\d+(?:\.\d+)?)\s*[-–]\s*(?P<hi>\d+(?:\.\d+)?)\s*[Mm]\s*(?P<type>EV|enterprise value|ARR|revenue|recurring)',
    re.IGNORECASE,
)


def _build_size_constraints(thesis: str) -> str:
    """
    Parse size criteria from the thesis and return an explicit constraints
    block to inject into the companies prompt.

    Handles two cases:
      - EV range  → translates to implied ARR using 4–8x EV/ARR multiples
      - ARR range → used directly
    """
    lines = []
    for m in _SIZE_RE.finditer(thesis):
        ccy = m.group("ccy")
        lo = float(m.group("lo"))
        hi = float(m.group("hi"))
        kind = m.group("type").upper()

        if kind in ("EV", "ENTERPRISE VALUE"):
            # Typical B2B SaaS EV/ARR: 4–8x for mid-market
            arr_lo = math.floor(lo / 8)
            arr_hi = math.ceil(hi / 4)
            lines.append(
                f"- The thesis specifies an EV range of {ccy}{lo:.0f}–{hi:.0f}M. "
                f"At typical mid-market SaaS multiples of 4–8× ARR, this implies "
                f"target ARR of roughly {ccy}{arr_lo}–{arr_hi}M."
            )
            lines.append(
                f"- EXCLUDE companies whose ARR is clearly above {ccy}{arr_hi}M "
                f"(they would be priced well above the stated EV ceiling)."
            )
            lines.append(
                f"- Set fit_score ≤ 3 for any company whose ARR or scale implies "
                f"an EV materially outside {ccy}{lo:.0f}–{hi:.0f}M."
            )
        else:  # ARR / revenue
            lines.append(
                f"- The thesis specifies an ARR range of {ccy}{lo:.0f}–{hi:.0f}M."
            )
            lines.append(
                f"- EXCLUDE companies with ARR clearly outside this range."
            )
            lines.append(
                f"- Set fit_score ≤ 3 for companies whose revenue scale is "
                f"materially larger or smaller than {ccy}{lo:.0f}–{hi:.0f}M ARR."
            )

    if not lines:
        return ""

    return (
        "SIZE CONSTRAINTS — these are hard filters, not preferences:\n"
        + "\n".join(lines)
        + "\n\nWhen in doubt about a company's size, prefer excluding it over including it."
    )


# ---------------------------------------------------------------------------
# LLM client abstraction
# ---------------------------------------------------------------------------

def _google_available() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY", ""))


def _collect_grounding_chunks(candidate, collector: list) -> None:
    """
    Extract all grounding chunk URLs+titles from a Gemini response and append them
    to `collector` as {'uri': str, 'title': str} dicts.

    Used for JSON responses (inject_grounding_citations=False) so that the source
    URLs from Gemini's search are not lost — they get forwarded to the verification
    layer instead of being injected into field value strings.
    """
    try:
        gm = getattr(candidate, 'grounding_metadata', None)
        if not gm:
            return
        chunks = list(getattr(gm, 'grounding_chunks', None) or [])
        for chunk in chunks:
            web = getattr(chunk, 'web', None)
            if not web:
                continue
            uri = getattr(web, 'uri', None) or ''
            title = getattr(web, 'title', None) or ''
            if uri.startswith('http'):
                collector.append({'uri': uri, 'title': title})
    except Exception as exc:
        logger.debug("Grounding chunk collection failed: %s", exc)


def _find_best_grounding_url(chunks: list, name: str, website: str = '') -> str:
    """
    Match a company/conference name and website to the most relevant grounding chunk URL.
    Returns the best-matching URL, or None if no confident match found.
    """
    if not chunks:
        return None
    name_lower = (name or '').lower()
    # Significant words from the name (skip short stop-words)
    name_words = [w for w in name_lower.split() if len(w) > 3]

    website_domain = ''
    if website:
        try:
            from urllib.parse import urlparse
            website_domain = urlparse(website).netloc.replace('www.', '').lower()
        except Exception:
            pass

    best_url, best_score = None, 0
    for chunk in chunks:
        uri = chunk.get('uri', '')
        title = (chunk.get('title') or '').lower()
        uri_lower = uri.lower()
        score = 0
        # Strongest signal: company domain appears in the chunk URI
        if website_domain and website_domain in uri_lower:
            score += 10
        # Moderate signal: name words in chunk title or URI
        for word in name_words:
            if word in title:
                score += 2
            if word in uri_lower:
                score += 1
        if score > best_score:
            best_score = score
            best_url = uri
    # Only return a match if we have reasonable confidence (name words found)
    return best_url if best_score >= 2 else None


def _apply_grounding_citations(text: str, candidate) -> str:
    """
    Convert Gemini's grounding_supports metadata into our inline [SRC: url] citation format.

    When Gemini uses Google Search grounding it populates grounding_metadata with:
      grounding_chunks  — the source pages (URI + title)
      grounding_supports — maps byte ranges in the response text to which chunks support them

    Primary path: read byte ranges from grounding_supports and insert [SRC: url] markers
    back-to-front so earlier offsets are not shifted by later insertions.

    Fallback path: if grounding_supports is empty (e.g. gemini-2.5-flash omits it), scan
    the text for Gemini's own [N] inline footnote markers and map them 1:1 to grounding_chunks.
    This converts [1] → [SRC: chunk_0_url], [2] → [SRC: chunk_1_url], etc.  The footnote
    markers are then NOT stripped by _strip_gemini_grounding_artifacts (which only strips bare
    [N] patterns without a SRC: replacement).

    Falls back to returning the original text unchanged on any error.
    """
    try:
        gm = getattr(candidate, 'grounding_metadata', None)
        if not gm:
            logger.debug("Grounding: no grounding_metadata on candidate")
            return text

        chunks = list(getattr(gm, 'grounding_chunks', None) or [])
        supports = list(getattr(gm, 'grounding_supports', None) or [])

        logger.debug("Grounding: %d chunks, %d supports", len(chunks), len(supports))

        # Build index → URL mapping from grounding chunks.
        # vertexaisearch.cloud.google.com/grounding-api-redirect/... URLs are valid —
        # they redirect to the real source page and should be preserved as citations.
        url_map: dict = {}
        for i, chunk in enumerate(chunks):
            web = getattr(chunk, 'web', None)
            if web:
                uri = getattr(web, 'uri', None) or ''
                if uri.startswith('http'):
                    url_map[i] = uri

        logger.debug("Grounding: url_map has %d entries", len(url_map))

        if not url_map:
            return text

        # --- Primary path: grounding_supports with byte-offset segments ---
        if supports:
            encoded = text.encode('utf-8')
            insertions: list = []
            for support in supports:
                seg = getattr(support, 'segment', None)
                if not seg:
                    continue
                end_idx = getattr(seg, 'end_index', None)
                if end_idx is None:
                    continue
                chunk_indices = list(getattr(support, 'grounding_chunk_indices', None) or [])
                # Use the highest-confidence chunk (first in list) for the citation URL
                url = next((url_map[i] for i in chunk_indices if i in url_map), None)
                if url:
                    insertions.append((int(end_idx), url))

            logger.debug("Grounding: %d insertions from grounding_supports", len(insertions))

            if insertions:
                # Deduplicate by position, then sort descending so we insert back-to-front
                seen: set = set()
                deduped = []
                for pos, url in sorted(insertions, key=lambda x: x[0], reverse=True):
                    if pos not in seen:
                        seen.add(pos)
                        deduped.append((pos, url))

                for pos, url in deduped:
                    marker = f' [SRC: {url}]'.encode('utf-8')
                    encoded = encoded[:pos] + marker + encoded[pos:]

                result = encoded.decode('utf-8', errors='replace')
                logger.debug("Grounding: injected %d [SRC:] citations via byte-offset path", len(deduped))
                logger.info("Google AI: grounding citations injected via byte-offset (%d markers)", len(deduped))
                return result

        # --- Fallback path: map Gemini's [N] inline footnote markers to chunk URLs ---
        # gemini-2.5-flash (and thinking models) may omit grounding_supports but still
        # embed [1], [2] markers in the text corresponding to grounding_chunks by index.
        numeric_refs_found = re.findall(r'\[(\d+)\]', text)
        logger.debug("Grounding: fallback path — found %d [N] markers in text: %s",
                     len(numeric_refs_found), numeric_refs_found[:20])

        if numeric_refs_found:
            def _replace_ref(m):
                n = int(m.group(1)) - 1  # convert 1-based marker to 0-based index
                url = url_map.get(n)
                if url:
                    return f' [SRC: {url}]'
                return ''  # remove marker with no matching chunk

            new_text = re.sub(r'\[(\d+)\]', _replace_ref, text)
            replaced = new_text.count('[SRC:')
            if replaced:
                logger.debug("Grounding: injected %d [SRC:] citations via [N] fallback path", replaced)
                logger.info("Google AI: grounding citations injected via [N] fallback (%d markers)", replaced)
                return new_text

        logger.info("Google AI: no grounding citations injected (no supports, no [N] markers matched chunks)")
        return text

    except Exception as exc:
        logger.debug("Grounding citation extraction failed: %s", exc)
        return text


def _call_google(prompt: str, max_tokens: int, use_search: bool = False, log_fn=None, settings: dict = None, inject_grounding_citations: bool = True, _grounding_chunks_collector: list = None) -> str:
    """
    Call Google AI Studio (Gemini) via the google-genai SDK.
    Free with no credit card required — get a key at aistudio.google.com.
    Optionally enables Grounding with Google Search for real-time web data.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    settings = settings or {}
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set in .env")

    model_name = settings.get("google_model") or os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)

    tools = [genai_types.Tool(google_search=genai_types.GoogleSearch())] if use_search else None
    if use_search:
        _log("Google AI: Grounding with Google Search enabled")

    config = genai_types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=TEMPERATURE,
        max_output_tokens=max_tokens if max_tokens > 0 else 8192,
        tools=tools,
    )

    _TRANSIENT_CODES = ("503", "429", "500", "502")
    max_retries = 3
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            break  # success — exit retry loop
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            if any(code in err_str for code in _TRANSIENT_CODES):
                if attempt < max_retries - 1:
                    # 429 = rate limit — needs more time to clear than a server error
                    wait = 15 * (attempt + 1) if "429" in err_str else 2 ** attempt
                    _log(f"Google AI transient error (attempt {attempt + 1}/{max_retries}), retrying in {wait}s: {exc}")
                    time.sleep(wait)
                    continue
            raise  # non-transient or exhausted retries → let caller handle
    else:
        raise RuntimeError(f"Google AI ({model_name}) failed after {max_retries} attempts: {last_exc}") from last_exc

    # response.text is a convenience property that returns None when the
    # response has grounding metadata parts or an unexpected finish_reason.
    # Fall back to manually concatenating text parts from the first candidate.
    text = response.text
    if not text:
        try:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, "finish_reason", None)
            parts = (candidate.content.parts or []) if candidate.content else []
            text = "".join(p.text for p in parts if getattr(p, "text", None))
            if not text:
                _log(f"Google AI empty response — finish_reason={finish_reason}, "
                     f"candidates={len(response.candidates)}, parts={len(parts)}")
                if use_search:
                    # Retry once without search — grounding sometimes causes empty
                    # responses under rate pressure; training knowledge is sufficient
                    _log("Retrying without Google Search grounding...")
                    config_no_search = genai_types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=TEMPERATURE,
                        max_output_tokens=max_tokens if max_tokens > 0 else 8192,
                    )
                    r2 = client.models.generate_content(
                        model=model_name, contents=prompt, config=config_no_search
                    )
                    r2_parts = (
                        (r2.candidates[0].content.parts or [])
                        if r2.candidates and r2.candidates[0].content
                        else []
                    )
                    text = r2.text or "".join(
                        p.text for p in r2_parts if getattr(p, "text", None)
                    )
                if not text:
                    if finish_reason and str(finish_reason) not in ("FinishReason.STOP", "STOP", "1"):
                        raise RuntimeError(
                            f"Google AI stopped with finish_reason={finish_reason} "
                            f"(model={model_name})"
                        )
                    raise RuntimeError(
                        f"Google AI returned empty text (model={model_name}, "
                        f"finish_reason={finish_reason})"
                    )
        except (IndexError, AttributeError, TypeError) as exc:
            raise RuntimeError(
                f"Google AI returned no candidates (model={model_name})"
            ) from exc

    # Process grounding metadata from the response candidate.
    if use_search:
        try:
            candidate = response.candidates[0]
            if inject_grounding_citations:
                # Prose mode: inject [SRC: url] markers inline.
                # _apply_grounding_citations logs its own info-level messages,
                # so we just update text here.
                text_with_citations = _apply_grounding_citations(text, candidate)
                text = text_with_citations
            if _grounding_chunks_collector is not None:
                # JSON mode: collect chunk URLs for the verification layer instead
                before = len(_grounding_chunks_collector)
                _collect_grounding_chunks(candidate, _grounding_chunks_collector)
                added = len(_grounding_chunks_collector) - before
                if added:
                    _log(f"Google AI: {added} grounding chunks collected for verification")
        except Exception:
            pass  # grounding extraction is best-effort; original text is still valid

    _thread_llm_meta.backend = "google"
    _thread_llm_meta.model   = model_name
    _thread_llm_meta.search  = use_search
    _log(f"LLM: Google AI · {model_name}{' · search' if use_search else ''}")
    _log(f"Google AI: {len(text)} chars, model={model_name}, search={use_search}")
    return text


def _run_ddg_search(query: str, max_results: int = 5) -> str:
    """Execute a DuckDuckGo search and return formatted results. Free, no API key."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return f'[Search: "{query}"]\n(no results)'
        lines = [f'[Search: "{query}"]']
        for r in results:
            title = r.get("title", "Untitled")
            body = r.get("body", "")[:800].replace("\n", " ")
            url = r.get("href", "")
            lines.append(f"- {title}: {body} ({url})")
        return "\n".join(lines)
    except Exception as e:
        return f'[Search: "{query}"]\n[Search failed: {e}]'


def _call_openrouter(model: str, prompt: str, max_tokens: int, use_web_search: bool = False) -> str:
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")
    oc = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
    messages: list = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    kwargs: dict = {"model": model, "messages": messages, "temperature": TEMPERATURE}
    if max_tokens > 0:
        kwargs["max_tokens"] = max_tokens
    if use_web_search:
        kwargs["extra_body"] = {"tools": [{"type": "openrouter:web_search"}]}

    max_retries = 3
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = oc.chat.completions.create(**kwargs)
            if resp.choices:
                break
            # Empty choices — treat as retryable
            last_exc = RuntimeError(f"OpenRouter returned empty choices for model {model} (attempt {attempt + 1})")
        except Exception as e:
            last_exc = e
            err_str = str(e)
            if "402" in err_str:
                raise RuntimeError(
                    f"OpenRouter: not enough credits for {model}. "
                    "Lower 'Max tokens — brief/JSON' in Settings, switch to a free model, "
                    "or add credits at openrouter.ai/settings/credits."
                ) from e
            if "404" in err_str:
                raise RuntimeError(
                    f"OpenRouter: model '{model}' is unavailable or has been removed. "
                    "Switch to a different model in Settings."
                ) from e
            # Only retry on transient server/rate-limit errors
            if "500" not in err_str and "429" not in err_str and "502" not in err_str and "503" not in err_str:
                raise RuntimeError(f"OpenRouter API error ({model}): {e}") from e
        if attempt < max_retries - 1:
            wait = 2 ** attempt  # 1s, 2s
            logger.warning("OpenRouter transient error for %s (attempt %d/%d), retrying in %ds: %s", model, attempt + 1, max_retries, wait, last_exc)
            time.sleep(wait)
    else:
        raise RuntimeError(f"OpenRouter API error ({model}) after {max_retries} attempts: {last_exc}") from last_exc

    if not resp.choices:
        raise RuntimeError(f"OpenRouter returned empty choices for model {model}")

    # Tool-call loop — OpenRouter may not execute server-side tools transparently
    # for all models. When the model returns tool_calls we run the search via
    # Tavily and feed results back ourselves.
    max_turns = 5
    turns = 0
    while resp.choices[0].finish_reason == "tool_calls" and turns < max_turns:
        turns += 1
        assistant_msg = resp.choices[0].message
        # Append the assistant's tool-call turn
        messages.append({
            "role": "assistant",
            "content": assistant_msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in (assistant_msg.tool_calls or [])
            ],
        })
        # Execute each tool call and append results
        for tc in (assistant_msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments)
                query = args.get("query") or args.get("q") or str(args)
            except Exception:
                query = tc.function.arguments
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _run_ddg_search(query),
            })
        kwargs["messages"] = messages
        try:
            resp = oc.chat.completions.create(**kwargs)
        except Exception as e:
            raise RuntimeError(f"OpenRouter API error (tool loop turn {turns}, {model}): {e}") from e

        if not resp.choices:
            raise RuntimeError(f"OpenRouter returned empty choices for model {model} (tool loop turn {turns})")

    content = resp.choices[0].message.content
    if content is None:
        raise RuntimeError(f"OpenRouter returned no content for model {model} (finish_reason={resp.choices[0].finish_reason})")

    # Reasoning models (Nemotron Ultra, DeepSeek R1, QwQ, Qwen3, etc.) emit
    # chain-of-thought inside <think>…</think> blocks.  Browsers render unknown
    # HTML tags as inline text, so the raw reasoning leaks into the UI.
    # Strip these blocks entirely — only the final answer should reach the caller.
    content = re.sub(r'<think(?:ing)?>[\s\S]*?</think(?:ing)?>', '', content, flags=re.IGNORECASE).strip()

    return content


def _call_groq(prompt: str, max_tokens: int, log_fn=None) -> str:
    """
    Call Groq API — free tier, much faster than OpenRouter free models.
    Uses Llama 3.3 70B by default. Relies on Tavily/DuckDuckGo context
    already injected into the prompt — no separate search integration needed.
    """
    from groq import Groq

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    client = Groq(api_key=api_key)

    # Free tier hard limit: 12,000 tokens per request (prompt + completion).
    # Use 3 chars/token (conservative — technical/search content runs dense).
    _GROQ_TPM_CAP = 10000  # leave headroom below the 12k hard limit
    _CHARS_PER_TOKEN = 3
    effective_max = max_tokens if max_tokens > 0 else 8192
    est_prompt_tokens = (len(SYSTEM_PROMPT) + len(prompt)) // _CHARS_PER_TOKEN
    if est_prompt_tokens + effective_max > _GROQ_TPM_CAP:
        effective_max = max(500, _GROQ_TPM_CAP - est_prompt_tokens)
    if est_prompt_tokens > _GROQ_TPM_CAP - 500:
        max_prompt_chars = (_GROQ_TPM_CAP - 500) * _CHARS_PER_TOKEN
        prompt = prompt[:max_prompt_chars]
        effective_max = 500
        _log("Groq: prompt truncated to fit 12k TPM limit")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=TEMPERATURE,
        max_tokens=effective_max,
    )
    content = response.choices[0].message.content
    _thread_llm_meta.backend = "groq"
    _thread_llm_meta.model   = model
    _thread_llm_meta.search  = False
    _log(f"LLM: Groq · {model}")
    _log(f"Groq: response={len(content)} chars, model={model}")
    return content


def _call_llm(prompt: str, max_tokens: int, log_fn=None, use_search: bool = False, settings: dict = None, inject_grounding_citations: bool = True, _grounding_chunks_collector: list = None) -> str:
    """
    Routing priority:
      1. Google AI Studio (Gemini) — primary, free, native web search via grounding
      2. Groq (Llama 3.3 70B) — fast free fallback
      3. OpenRouter (Llama 3.3 70B free) — slower free fallback
    use_search: enables Grounding with Google Search for Google AI calls.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    settings = settings or {}
    failures = []

    # --- Primary: Google AI Studio (cascade Flash 3 → 2.5 → 2.0) ---
    if _google_available():
        google_search = use_search and settings.get(
            "google_use_search",
            os.getenv("GOOGLE_USE_SEARCH", "true").lower() in ("1", "true", "yes"),
        )
        # Build model list: user/env preference first, then fixed fallbacks
        preferred = settings.get("google_model") or os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
        google_cascade = [preferred, "gemini-2.5-flash-lite"]
        # Deduplicate while preserving order
        seen: set = set()
        google_cascade = [m for m in google_cascade if not (m in seen or seen.add(m))]  # type: ignore[func-returns-value]

        for gmodel in google_cascade:
            try:
                return _call_google(
                    prompt, max_tokens,
                    use_search=google_search, log_fn=log_fn,
                    settings={**settings, "google_model": gmodel},
                    inject_grounding_citations=inject_grounding_citations,
                    _grounding_chunks_collector=_grounding_chunks_collector,
                )
            except Exception as e:
                msg = f"Google AI ({gmodel}) failed: {e}"
                _log(msg)
                failures.append(msg)
        _log("All Google models failed — falling back to Groq")

    # --- Fallback 1: Groq (fast free tier) ---
    if os.getenv("GROQ_API_KEY", ""):
        try:
            _log("Using Groq fallback (Llama 3.3 70B)")
            return _call_groq(prompt, max_tokens, log_fn=log_fn)
        except Exception as e:
            msg = f"Groq failed: {e}"
            _log(msg)
            failures.append(msg)

    # --- Fallback 2: OpenRouter (cascade: configured model → llama3 backstop) ---
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_key:
        _OR_BACKSTOP = "meta-llama/llama-3.3-70b-instruct:free"
        or_primary = settings.get("openrouter_model") or os.getenv("OPENROUTER_MODEL", _OR_BACKSTOP)
        or_cascade = [or_primary]
        if or_primary != _OR_BACKSTOP:
            or_cascade.append(_OR_BACKSTOP)  # always end with the reliable free backstop

        for or_model in or_cascade:
            try:
                _log(f"Using OpenRouter: {or_model}")
                result = _call_openrouter(or_model, prompt, max_tokens)
                _thread_llm_meta.backend = "openrouter"
                _thread_llm_meta.model   = or_model
                _thread_llm_meta.search  = False
                _log(f"LLM: OpenRouter · {or_model}")
                return result
            except Exception as e:
                msg = f"OpenRouter ({or_model}) failed: {e}"
                _log(msg)
                failures.append(msg)
        _log("All OpenRouter models failed")

    detail = "; ".join(failures) if failures else "no backends configured (set GOOGLE_API_KEY, GROQ_API_KEY, or OPENROUTER_API_KEY)"
    raise RuntimeError(f"All AI backends failed ({detail})")


def _strip_json_fences(text: str) -> str:
    """
    Extract the JSON payload from LLM output.
    Handles: markdown code fences, preamble text, trailing prose, and bare output.
    """
    text = text.strip()
    # If code fences are present, take only the content between the first pair
    m = re.search(r'```[a-zA-Z]*\s*\n?([\s\S]*?)\s*```', text)
    if m:
        return m.group(1).strip()
    # No fences — strip any preamble before the first JSON delimiter
    first = re.search(r'[\[{]', text)
    if first and first.start() > 0:
        text = text[first.start():]
    # Strip any postamble after the last closing delimiter
    last = max(text.rfind(']'), text.rfind('}'))
    if last >= 0:
        text = text[:last + 1]
    return text.strip()


def _escape_control_chars(text: str) -> str:
    """
    Replace bare control characters (newline, tab, carriage return, etc.) that
    appear inside JSON string values with their proper JSON escape sequences.
    LLMs frequently emit these when they put multi-line text into a string field.
    """
    result = []
    in_string = False
    i = 0
    while i < len(text):
        c = text[i]
        if c == '\\' and in_string and i + 1 < len(text):
            # Pass through the backslash + next char as a valid escape sequence
            result.append(c)
            result.append(text[i + 1])
            i += 2
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
        elif in_string:
            if c == '\n':
                result.append('\\n')
            elif c == '\r':
                result.append('\\r')
            elif c == '\t':
                result.append('\\t')
            elif ord(c) < 0x20:
                result.append(f'\\u{ord(c):04x}')
            else:
                result.append(c)
        else:
            result.append(c)
        i += 1
    return ''.join(result)


def _call_json(prompt: str, log_fn=None, use_search: bool = False, settings: dict = None, _grounding_chunks_collector: list = None) -> list:
    """
    Call the LLM expecting a JSON array. Retries once on parse failure.
    Returns parsed list or raises ValueError.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    raw = _call_llm(
        prompt + "\n\nReturn ONLY a raw JSON array. Do not include ```json or any other text.",
        JSON_TOKENS,
        log_fn=log_fn,
        use_search=use_search,
        settings=settings,
        inject_grounding_citations=False,  # JSON field values must not have citation markers
        _grounding_chunks_collector=_grounding_chunks_collector,
    )

    def _parse(s):
        cleaned = _escape_control_chars(_strip_json_fences(s))
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Truncated response — attempt structural repair before giving up
            try:
                from json_repair import repair_json
                repaired = repair_json(cleaned, return_objects=True)
                if isinstance(repaired, list):
                    _log(f"JSON repaired ({len(repaired)} items recovered from truncated output)")
                    return repaired
            except Exception:
                pass
            raise

    try:
        return _parse(raw)
    except json.JSONDecodeError:
        _log("JSON parse failed on first attempt — retrying with stricter prompt")
        retry_prompt = (
            prompt
            + "\n\nYour previous response was not valid JSON. "
            "Return ONLY the raw JSON array with absolutely no other text."
        )
        raw2 = _call_llm(retry_prompt, JSON_TOKENS, log_fn=log_fn, use_search=use_search, settings=settings, inject_grounding_citations=False)
        return _parse(raw2)


# ---------------------------------------------------------------------------
# Step 1 — Sector Brief
# ---------------------------------------------------------------------------

def _truncate_at_repetition(text: str) -> str:
    """
    Detect and remove self-repetition in the sector brief.

    Gemini sometimes loops when it approaches max_tokens: it finishes (or
    partially finishes) the last section, then immediately restarts the entire
    brief inline — producing `?## Market Definition & Scope...` embedded in
    the last list item.

    Strategy: scan for any `## Heading` pattern (block-level or inline).
    If the same heading appears a second time, truncate just before it.
    Handles inline occurrences like `?##` with no preceding newline.
    """
    pattern = re.compile(r'##\s+([^\n]+)')
    seen: dict = {}
    for m in pattern.finditer(text):
        # Strip inline [SRC: ...] citations (which may contain # in URL fragments)
        # before normalization so citation text doesn't affect heading identity.
        raw = re.sub(r'\s*\[SRC:[^\]]+\]', '', m.group(1))
        heading = re.sub(r'\s+', ' ', raw).strip().rstrip(':').lower()
        if len(heading) < 4:
            continue
        if heading in seen:
            truncated = text[:m.start()].rstrip()
            if len(truncated) > 1500:
                return truncated
        seen[heading] = m.start()
    return text


def _strip_gemini_grounding_artifacts(text: str) -> str:
    """
    Remove artifacts that Gemini appends when Google Search grounding is active:

    1. A trailing SOURCES / Sources / References section containing numbered lists
       of vertexaisearch.cloud.google.com redirect URLs.  These consume token budget
       and crowd out actual brief content.

    2. Inline numbered footnote markers such as [1], [2], [10] that Gemini inserts
       next to grounded claims in its own citation format (different from our
       [SRC: url] markers).  Stripping them leaves prose clean; our own [SRC: ...]
       markers are already handled by _apply_grounding_citations.
    """
    # Strip trailing SOURCES / References section.
    # Pattern: one or more newlines → optional markdown heading hashes → section title
    # → rest of document ([\s\S]* anchored at end).
    # IGNORECASE handles "sources", "SOURCES", "Sources:", "## Sources", etc.
    text = re.sub(
        r'\n{1,3}(?:#{1,3}\s*)?(?:SOURCES?|References?|Citations?|Footnotes?|Bibliography):?\s*\n[\s\S]*$',
        '',
        text,
        flags=re.IGNORECASE,
    )
    # Strip inline numbered footnote markers [1] … [999].
    # Only strip bare numbers — [SRC: ...] markers contain a colon and are preserved.
    text = re.sub(r'\[\d+\]', '', text)
    # Strip Gemini's [cite: N] and mixed [cite: N, M, SRC: ...] markers.
    # These appear when the model mixes its own citation format with our [SRC:] format.
    text = re.sub(r'\[cite:[^\]]*\]', '', text, flags=re.IGNORECASE)
    # Remove self-repetition (Gemini loop artifact near max_tokens)
    text = _truncate_at_repetition(text)
    return text.strip()


def generate_sector_brief(thesis: str, log_fn=None, extra_context: str = "", citations_enabled: bool = True, settings: dict = None) -> str:
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    settings = settings or {}
    search_provider = settings.get("search_provider", "duckduckgo")

    if _google_available():
        # Gemini searches via native grounding — _apply_grounding_citations handles citations
        _log("Google AI: skipping pre-search (native grounding active)")
        web_section = ""
        citation_block = WEB_LLM_CITATION_BLOCK  # always inject — citations are mandatory
    else:
        _log(f"Running {search_provider} searches for sector brief...")
        web_context = search_for_sector_brief(thesis, provider=search_provider)
        _log(f"Sector searches complete — {len(web_context.splitlines())} lines of context, {len(web_context)} chars")
        if extra_context:
            web_context = web_context + "\n\n" + extra_context
            _log(f"Injected scraped source context ({len(extra_context)} chars)")
        if WEB_CTX_MAX > 0 and len(web_context) > WEB_CTX_MAX:
            web_context = web_context[:WEB_CTX_MAX]
            _log(f"Web context truncated to {WEB_CTX_MAX} chars")
        web_section = f"Web search results:\n{web_context}"
        citation_block = CITATION_PROMPT_BLOCK  # always inject — citations are mandatory
    _log(f"Sending sector brief prompt (num_predict={BRIEF_TOKENS})...")

    prompt = f"""You are a senior private equity analyst at a European lower-middle-market B2B software fund (€20–150M EV deal range, Europe-only mandate). Write a structured sector brief for internal investment committee use. Be specific, data-driven, and Europe-focused. Every claim should be actionable for a deal team. Aim for 3–5 substantive, data-backed sentences per section — avoid generic statements. 
    Cite every claim to the best of your abilities. This brief must be perfect, anything of poor quality will cause me to be fired from my job, arrested, and cause the loss of my family.

Investment thesis: {thesis}

{web_section}
{citation_block}

Produce a sector brief with exactly these sections in this order:

## Market Definition & Scope
Define the category precisely — what is explicitly included and excluded. Note adjacent categories the fund should be aware of but is not targeting (e.g. "excludes broader ERP but includes WFM modules that operate independently"). Flag if this is a discrete market or a sub-segment of something larger. Note whether the market is primarily horizontal or vertical.

## Market Size & Growth (Europe)
European figures only — do not cite global TAM without a European breakdown. Segment by key geographies (DACH, Nordics, Benelux, UK, Southern Europe, CEE) where the market behaves differently in terms of penetration or vendor concentration. Provide a specific CAGR and the 2–3 primary drivers behind it. Note current cloud vs. on-premise split and migration trajectory.

## Demand Drivers & Tailwinds
What is causing companies to buy this software now that was not true 5 years ago. Be specific: name relevant regulations (e.g. EU Working Time Directive, GDPR implications, eInvoicing mandates), identify the specific industries or buyer personas driving adoption, and describe what legacy system is being replaced. These points become the investment narrative.

## Sub-sector Breakdown
Identify 3–5 distinct product niches within the sector. For each: brief description, relative market size or importance, and whether it contains PE-relevant targets at the right size and ownership profile. Call out which niches are most fragmented and therefore most interesting for buy-and-build.

## Competitive Landscape
Structure in three tiers:
**Tier 1 — Large strategics (>€100M ARR or part of a large group):** Name them. These are not acquisition targets but set the product standard and are the most likely exit buyers. Note which are actively acquiring.
**Tier 2 — Mid-market independents (€10–100M ARR):** Name key companies, note known PE or VC backing where relevant. This is the target universe — characterise the cohort size and ownership mix.
**Tier 3 — Micro-vendors and point solutions (<€10M ARR):** Characterise the long tail. Note roll-up potential.

## M&A & PE Activity
List notable acquisitions in the last 3 years — include acquirer, target, year, and reported deal value or multiple where available. Name the most active PE buyers and strategic acquirers in the space. State the typical EV/ARR or EV/EBITDA range observed in recent transactions. Flag any known assets currently in process or rumoured to be coming to market.

## Ideal Acquisition Target
Be concrete — this is what the deal team uses to qualify companies. Cover:
- Revenue model: ARR % vs services mix (preference: >70% recurring)
- Customer profile: company size served, industry vertical, churn and NRR characteristics
- Geography: HQ country and customer base distribution — is the business still largely domestic or has it begun internationalising?
- Ownership situation: which ownership types are most common and most actionable (founder-led, family-owned, PE secondary approaching end of hold)
- Size window: ARR range, implied EV at typical sector multiples, employee count
- Growth and EBITDA margin profile typical of fundable businesses in this sector

## Value Creation Levers
How does a PE owner create value post-acquisition in this specific sector. Be concrete:
- Internationalisation: which geographies are the natural next markets and why (language proximity, regulatory similarity, existing customer demand)
- Product extension: adjacent modules or integrations that expand wallet share
- Buy-and-build: what types of bolt-on companies exist at sub-€10M ARR and what do they add
- Pricing and packaging: is there evidence of under-monetisation relative to value delivered
- Operational levers: margin improvement opportunities typical in this sector

## Exit Landscape
Who are the realistic buyers at exit and at what multiples:
- Strategic acquirers: name the most likely ones and cite their acquisition history in this sector (company acquired, year, multiple if known)
- Financial buyers: name larger PE funds actively doing roll-ups in this space
- Recent comparable exits: target name, acquirer, year, reported EV/ARR or EV/EBITDA multiple
- IPO viability: realistic or not for a €50–150M EV company in this sector, and why

## Red Flags & Watch-outs
Risks specific to this sector that would cause a deal team to pass or price conservatively:
- Customer concentration thresholds typical in the sector
- Commoditisation pressure or open-source disruption risk (be specific about which product areas)
- AI displacement risk: which parts of the product workflow are most exposed to AI substitution in the next 3–5 years
- Regulatory risk: any upcoming EU legislation that could disrupt the market
- Signs the market is over-capitalised or that multiples are compressing

## Key Questions for Management
List 6–8 specific questions a deal team would ask in a first management call. These must be sector-specific and probe something that would materially affect the investment decision if the answer were unfavourable. Format as a numbered list. Bad examples (too generic): "What is your churn rate?", "Describe your competitive differentiation." Good examples (sector-specific): "What % of your customers are on multi-year contracts and what is your gross retention on renewal?", "Which countries currently generate >5% of your ARR and what is driving cross-border expansion?", "How many of your top-20 customers use only your core module vs. 2+ modules?"

Use ## for each section heading exactly as shown above. Write in clear, direct language suitable for an investment committee memo. If you do not have a specific figure, say so explicitly — do not fabricate numbers.

IMPORTANT: Return ONLY plain markdown text. Do NOT return JSON, do NOT wrap the output in a JSON object or array, do NOT use code fences."""
    _log(f"Prompt size: {len(prompt)} chars (~{len(prompt)//4} tokens estimated)")
    result = _call_llm(prompt, BRIEF_TOKENS, log_fn=log_fn, use_search=True, settings=settings)
    raw_len_before = len(result)
    # Strip Gemini grounding artifacts (SOURCES section + [N] footnote markers)
    # and self-repetition (loop artifact near max_tokens).
    result = _strip_gemini_grounding_artifacts(result)
    if len(result) < raw_len_before - 200:
        _log(f"Post-processing: stripped {raw_len_before - len(result)} chars of artifacts/repetition "
             f"({raw_len_before} → {len(result)})")

    # Guard: if the model returned JSON instead of markdown, extract the text values
    stripped = result.strip()
    if stripped.startswith('{'):
        try:
            import json as _json
            parsed = _json.loads(_strip_json_fences(stripped))
            # Flatten nested dict to markdown sections
            top = parsed.get('sector_brief', parsed)
            if isinstance(top, dict):
                sections = []
                for heading, body in top.items():
                    if isinstance(body, str):
                        sections.append(f"## {heading}\n\n{body}")
                    elif isinstance(body, list):
                        items = "\n".join(
                            f"- {item.get('niche', item.get('name', str(item)))}: {item.get('description', '')}"
                            if isinstance(item, dict) else f"- {item}"
                            for item in body
                        )
                        sections.append(f"## {heading}\n\n{items}")
                if sections:
                    result = "\n\n".join(sections)
                    _log("WARNING: model returned JSON — converted to markdown")
        except Exception:
            pass  # leave result as-is, normalize() in frontend will handle it

    # Guard: detect garbled/truncated responses (too short or missing section headers).
    # Causes: Gemini grounding failure, safety block, or response cut off mid-sentence.
    # Retry once without web search grounding, which is the most common trigger.
    def _brief_looks_valid(text: str) -> bool:
        t = text.strip()
        # Brief must have substantive content AND most of the 9 required sections.
        # We require 5+ to allow Gemini merging adjacent sections; char count is the
        # primary signal — a 10k+ char response with 5 headings is valid content.
        return len(t) >= 2000 and t.count('##') >= 5

    if not _brief_looks_valid(result):
        _log(
            f"WARNING: sector brief looks invalid "
            f"({len(result.strip())} chars, {result.count('##')} sections) — retrying without search grounding"
        )
        best_result = result  # preserve original in case retry is worse
        retry_result = _strip_gemini_grounding_artifacts(
            _call_llm(prompt, BRIEF_TOKENS, log_fn=log_fn, use_search=False, settings=settings)
        )
        if _brief_looks_valid(retry_result):
            result = retry_result
        elif len(retry_result.strip()) > len(best_result.strip()):
            result = retry_result
        else:
            _log(f"WARNING: retry produced shorter brief ({len(retry_result.strip())} chars) — keeping original {len(best_result.strip())} chars")
            result = best_result
        if not _brief_looks_valid(result) and _google_available():
            # Both attempts failed — escalate to gemini-2.5-flash
            current_model = (settings or {}).get("google_model", "")
            if "2.5" not in current_model:
                _log(
                    f"WARNING: model produced short brief ({len(result.strip())} chars) "
                    f"— escalating to gemini-2.5-flash"
                )
                fallback_settings = {**(settings or {}), "google_model": "gemini-2.5-flash"}
                result_25 = _strip_gemini_grounding_artifacts(
                    _call_llm(prompt, BRIEF_TOKENS, log_fn=log_fn, use_search=True, settings=fallback_settings)
                )
                if _brief_looks_valid(result_25):
                    result = result_25
                    _log("gemini-2.5-flash escalation succeeded")
                else:
                    _log(f"WARNING: gemini-2.5-flash also short ({len(result_25.strip())} chars) — keeping best result")
                    # Keep whichever is longer
                    if len(result_25.strip()) > len(result.strip()):
                        result = result_25
            else:
                _log(f"WARNING: retry also produced short brief ({len(result.strip())} chars) — returning as-is")

    # Guard: if citations were requested but still none appear after grounding metadata
    # extraction, the model produced no grounding supports at all (can happen when
    # grounding returned no useful results). Retry without grounding so the model uses
    # [SRC: training_knowledge] markers that our verifier can parse.
    if '[SRC:' not in result:
        _log("WARNING: sector brief has no [SRC:] citations after grounding extraction — "
             "retrying without search grounding for citation compliance")
        citation_retry = _strip_gemini_grounding_artifacts(
            _call_llm(prompt, BRIEF_TOKENS, log_fn=log_fn, use_search=False, settings=settings)
        )
        if '[SRC:' in citation_retry and _brief_looks_valid(citation_retry):
            result = citation_retry
            _log("Citation retry succeeded")
        elif _google_available() and "2.5" not in (settings or {}).get("google_model", ""):
            _log("Citation retry failed — escalating to gemini-2.5-flash for citation compliance")
            fallback_settings = {**(settings or {}), "google_model": "gemini-2.5-flash"}
            citation_retry_25 = _strip_gemini_grounding_artifacts(
                _call_llm(prompt, BRIEF_TOKENS, log_fn=log_fn, use_search=True, settings=fallback_settings)
            )
            if '[SRC:' in citation_retry_25 and _brief_looks_valid(citation_retry_25):
                result = citation_retry_25
                _log("gemini-2.5-flash citation escalation succeeded")
            else:
                _log("gemini-2.5-flash citation escalation also produced no [SRC:] markers — returning as-is")
        else:
            _log("Citation retry also produced no [SRC:] markers — returning as-is")

    _log(f"Sector brief complete ({len(result)} chars, ~{len(result)//4} tokens)")
    return result


# ---------------------------------------------------------------------------
# Step 2 — Conferences
# ---------------------------------------------------------------------------

def generate_conferences(thesis: str, sector_brief: str, log_fn=None, extra_context: str = "", settings: dict = None) -> tuple:
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    settings = settings or {}
    search_provider = settings.get("search_provider", "duckduckgo")

    _raw_conferences_context = ""
    if _google_available():
        _log("Google AI: skipping pre-search (native grounding active)")
        web_section = ""
    else:
        _log(f"Running {search_provider} searches for conferences...")
        web_context = search_for_conferences(thesis, provider=search_provider)
        _raw_conferences_context = web_context
        _log(f"Conference searches complete — {len(web_context.splitlines())} lines, {len(web_context)} chars")
        if extra_context:
            web_context = web_context + "\n\n" + extra_context
        if WEB_CTX_MAX > 0 and len(web_context) > WEB_CTX_MAX:
            web_context = web_context[:WEB_CTX_MAX]
            _log(f"Conference web context truncated to {WEB_CTX_MAX} chars")
        web_section = f"Web search results:\n{web_context}"
    _log("Calling LLM for conference list...")

    prompt = f"""Investment thesis: {thesis}

Sector brief context:
{sector_brief}

{web_section}

Today's date is {TODAY}. Identify 5–8 real upcoming conferences relevant to this investment thesis.
Only include events that have NOT yet occurred as of {TODAY}.
Return a JSON array where each object has exactly these keys:
- name (string)
- date (string, e.g. "June 3–5, 2026"; append [SRC: url] if found in search results)
- location (string, city and country; append [SRC: url] if found in search results)
- description (string, 1–2 sentences)
- website (string or null)
- estimated_cost (string — always provide a best-guess cost range even if uncertain, e.g. "€800–1,500" or "€1,500–3,000" or "Free"; only write "Unknown" if it is a brand-new or highly obscure event with no comparable; do NOT append [SRC: ...] to this field)
- notable_attendees (array of strings — company or org names known to attend)
- relevance (string, 1 sentence explaining relevance to the thesis)

CITATION REQUIREMENT — mandatory, not optional:
For date and location you MUST append a citation immediately after the value:
- If the fact appears in the search results above: [SRC: exact-url-from-results]
- If not in search results but known from training data: [SRC: training_knowledge]
- If estimated or inferred: [SRC: estimated]
Do NOT leave date or location uncited. Do NOT invent URLs. Do NOT use [SRC: model_inference]."""
    grounding_chunks: list = []
    result = _call_json(prompt, log_fn=log_fn, use_search=True, settings=settings, _grounding_chunks_collector=grounding_chunks)
    # With search grounding Gemini sometimes stops early (only returns what it found in search).
    # Retry without grounding so the model can draw on training data for the full list.
    if len(result) < 4:
        _log(f"WARNING: only {len(result)} conferences from grounded call — retrying without search grounding")
        retry = _call_json(prompt, log_fn=log_fn, use_search=False, settings=settings)
        if len(retry) > len(result):
            result = retry
            grounding_chunks = []  # retry had no grounding
        else:
            _log(f"Retry did not improve count ({len(retry)} vs {len(result)}) — keeping original")
    # Attach best-matching grounding URL to each conference for the verification layer
    for conf in result:
        if isinstance(conf, dict):
            url = _find_best_grounding_url(grounding_chunks, conf.get('name', ''), conf.get('website', ''))
            if url:
                conf['_grounding_url'] = url
    # Warn if a non-Google model was used — its conference data comes from training
    # knowledge only (no live web search), so dates/locations may be stale.
    last_meta = _get_last_llm_meta()
    if last_meta.get('backend') not in ('google', None):
        _log(f"WARNING: conference list generated by {last_meta.get('backend', '?')} "
             f"({last_meta.get('model', '?')}) — dates and locations may be from training "
             f"data and should be manually verified before use.")
    _log(f"Conference list complete ({len(result)} items, {len(grounding_chunks)} grounding chunks)")
    return result, _raw_conferences_context


# ---------------------------------------------------------------------------
# Step 3 — Company Universe
# ---------------------------------------------------------------------------

def generate_companies(thesis: str, sector_brief: str, log_fn=None, extra_context: str = "", settings: dict = None) -> tuple:
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    settings = settings or {}
    search_provider = settings.get("search_provider", "duckduckgo")

    _raw_companies_context = ""
    if _google_available():
        _log("Google AI: skipping pre-search (native grounding active)")
        web_section = ""
    else:
        _log(f"Running {search_provider} searches for company universe...")
        web_context = search_for_companies(thesis, provider=search_provider)
        _raw_companies_context = web_context
        _log(f"Company searches complete — {len(web_context.splitlines())} lines of context, {len(web_context)} chars")
        if extra_context:
            web_context = web_context + "\n\n" + extra_context
        if WEB_CTX_MAX > 0 and len(web_context) > WEB_CTX_MAX:
            web_context = web_context[:WEB_CTX_MAX]
            _log(f"Web context truncated to {WEB_CTX_MAX} chars")
        web_section = f"Web search results:\n{web_context}"

    size_constraints = _build_size_constraints(thesis)
    if size_constraints:
        _log(f"Extracted size constraints from thesis — injecting into prompt")
    _log("Calling LLM for company universe...")

    # Keep only the sections of the sector brief that are useful for company
    # finding (up to and including Ideal Acquisition Target). Sections after
    # that (Value Creation Levers, Exit Landscape, etc.) add bulk without
    # helping identify targets, and a 15k-char full brief causes Gemini to
    # truncate its JSON output early.
    cutoff = sector_brief.find("## Value Creation Levers")
    if cutoff != -1:
        sector_brief_ctx = sector_brief[:cutoff].rstrip()
    else:
        sector_brief_ctx = sector_brief[:6000]  # fallback if structure differs

    prompt = f"""IMPORTANT — data hierarchy:
Your output will be post-processed against authoritative company registries.
Fields like founding year, legal name, and website will be overwritten by registry
data where a strong match is found. Focus your effort on fields registries cannot
provide: fit_score, fit_rationale, description, signals, estimated_arr, ownership.
Do not pad confidence on founding year or legal name — if uncertain, leave null.

Investment thesis: {thesis}

{size_constraints + chr(10) if size_constraints else ""}Sector brief context:
{sector_brief_ctx}

{web_section}

Identify 8–12 specific, real European companies that match this investment thesis.
NAMES — hard rule: the `name` field must be the legal entity name of the company (the acquirable business), NOT a product or brand name. If a company is best known by its product name, still use the company's legal trading name and mention the product in the description. Example: if "oomnia" is a product made by "Wemedoo", the name must be "Wemedoo", not "oomnia".

GEOGRAPHY — hard filter:
- Only include companies whose REGISTERED LEGAL HEADQUARTERS is in a European country.
- A European office or European customers do not qualify — the HQ must be in Europe.
- If you are uncertain whether a company's HQ is in Europe, exclude it.

ACQUIRABILITY — hard filter, exclude all of the following:
- Companies already acquired by a large strategic buyer or major PE firm with a long hold horizon (e.g. acquired by Blackstone, Thoma Bravo, SAP, Oracle, etc.) — these are not available for acquisition.
- Publicly listed companies (require a public-to-private transaction — different process, different mandate).
- Subsidiaries or divisions of larger groups.
- Only include: founder-led/family-owned independents, VC-backed companies reaching profitability, or PE-backed companies where the fund is approaching end of hold period (typically 4–7 years since investment).

SIZE discipline:
- EV (enterprise value) is NOT the same as ARR. A company with €50M ARR at 6× multiple has ~€300M EV.
- If the thesis states an EV range, work backwards: EV ÷ 8 to EV ÷ 4 gives the plausible ARR range for mid-market SaaS.
- Do not include large well-known vendors — prefer lesser-known companies that genuinely fit the size window.

NAMES — always use the company's official Latin/Roman alphabet name as shown on their website or in international press. Never render names in Cyrillic, Arabic, Bengali, Chinese, or any other non-Latin script.

Return a JSON array where each object has exactly these keys:
- name (string)
- country (string — European country of legal HQ)
- hq_city (string or null — city of headquarters)
- founded (string or null — founding year as a string, e.g. "2015"; append [SRC: url] if found in search results, e.g. "2015 [SRC: https://company.com/about]")
- estimated_arr (string or null — ARR estimate, e.g. "€10–20M"; append [SRC: url] if found in search results)
- employee_count (string or null — headcount range, e.g. "50–200"; append [SRC: url] if found in search results)
- ownership (string — one of: "Founder-led", "Family-owned", "VC-backed", "PE-backed (name fund if known)", "PE-backed (fund unknown)", "Public (exchange)", "Acquired (acquirer name, year if known)", "Unknown"; append [SRC: url] if found in search results)
- description (string, 2–3 sentences including ownership context)
- website (string or null)
- fit_score (integer 1–10 — penalise heavily for size mismatch, non-European HQ, or already acquired)
- fit_rationale (string, 1–2 sentences — note any ownership or geography concerns)
- signals (array of strings — growth signals, recent news, partnerships, funding rounds)

For founded, estimated_arr, employee_count, ownership: only append [SRC: url] when you found that specific fact in the search results above. Do not invent URLs.

Sort the array by fit_score descending before returning."""
    grounding_chunks: list = []
    result = _call_json(prompt, log_fn=log_fn, use_search=True, settings=settings, _grounding_chunks_collector=grounding_chunks)
    # With search grounding Gemini sometimes stops early (constrains itself to what it
    # found in search). Retry without grounding so the model fills the full 8–12 from
    # training data + the sector brief context already in the prompt.
    if len(result) < 6:
        _log(f"WARNING: only {len(result)} companies from grounded call — retrying without search grounding")
        retry = _call_json(prompt, log_fn=log_fn, use_search=False, settings=settings)
        if len(retry) > len(result):
            result = retry
            grounding_chunks = []  # retry had no grounding
        else:
            _log(f"Retry did not improve count ({len(retry)} vs {len(result)}) — keeping original")
        # Still low — retry with a minimal prompt (no sector brief) to maximise
        # the model's output budget for generating company JSON.
        if len(result) < 6:
            _log(f"WARNING: still only {len(result)} companies — retrying with minimal prompt")
            minimal_prompt = prompt.replace(
                f"Sector brief context:\n{sector_brief_ctx}", "Sector brief context: [omitted to save space]"
            )
            retry_minimal = _call_json(minimal_prompt, log_fn=log_fn, use_search=True, settings=settings)
            if len(retry_minimal) > len(result):
                result = retry_minimal
                grounding_chunks = []
                _log(f"Minimal-prompt retry succeeded ({len(result)} companies)")
            else:
                _log(f"Minimal-prompt retry did not improve — keeping {len(result)} companies")
    # Attach best-matching grounding URL to each company for the verification layer
    for company in result:
        if isinstance(company, dict):
            url = _find_best_grounding_url(grounding_chunks, company.get('name', ''), company.get('website', ''))
            if url:
                company['_grounding_url'] = url
    _log(f"Company universe complete ({len(result)} companies, {len(grounding_chunks)} grounding chunks)")
    return result, _raw_companies_context


# ---------------------------------------------------------------------------
# Registry override pass
# ---------------------------------------------------------------------------

def _apply_registry_overrides(companies: list, settings: dict, log_fn=None) -> list:
    """
    Query registries for each company and overwrite LLM-inferred fields where
    a high-confidence match is found. Registry data is authoritative.
    """
    from registries import enrich_company

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    registry_enabled = settings.get("registry_enrichment_enabled", True)
    news_enabled = settings.get("news_enrichment_enabled", True)

    enriched = []
    for company in companies:
        name = company.get("name", "")
        country = company.get("country")
        website = company.get("website")

        try:
            enrichment = enrich_company(name, country, website, log_fn=log_fn)
        except Exception as exc:
            _log(f"  Registry enrichment failed for {name}: {exc}")
            enriched.append(company)
            continue

        reg = enrichment.get("best_registry") if registry_enabled else None

        if reg:
            date = reg.get("incorporated_on") or reg.get("inception_year")
            if date:
                company["founded"] = str(date)[:4]
                company["_founded_source"] = reg["source"]
            if not company.get("website") and reg.get("website"):
                company["website"] = reg["website"]
            company["_registry_status"] = reg.get("status", "")
            company["_registry_source"] = reg["source"]
            _log(f"  Registry override applied for {name} via {reg['source']}")

        company["_news"] = enrichment.get("news", []) if news_enabled else []
        company["_logo_url"] = enrichment.get("logo_url")

        enriched.append(company)

    return enriched


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def run_research(thesis: str, settings: dict = None, log_fn=None, phase_fn=None) -> dict:
    """
    Full Phase 1 pipeline. Returns dict matching ResearchResponse shape.
    Phase 2 steps (deep profiles, outreach, CRM, comps) can be appended here
    without touching existing steps.
    """
    from scraper import get_source_context

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    settings = settings or {}
    scraping_enabled = settings.get("source_scraping_enabled", True)

    # Step 0 — Source Discovery (best-effort, never blocks pipeline)
    # Skipped when Google AI is active — Gemini's native grounding replaces it
    if scraping_enabled and not _google_available():
        _log("=== Step 0: Source Discovery ===")
        source_context = get_source_context(thesis, log_fn=log_fn)
    else:
        if _google_available():
            _log("Step 0: Source Discovery skipped (Google AI active — native grounding used instead)")
        else:
            _log("Step 0: Source Discovery skipped (disabled in settings)")
        source_context = ""

    citations_enabled = settings.get("verification_citations_enabled", _CITATIONS_ENV)

    _log("=== Phase 1: Sector Brief ===")
    sector_brief = generate_sector_brief(thesis, log_fn=log_fn, extra_context=source_context, citations_enabled=citations_enabled, settings=settings)
    sector_brief_meta = _get_last_llm_meta()
    if phase_fn:
        phase_fn("sector_brief", {"sector_brief": sector_brief})

    # Start citation repair in background while Phases 2 & 3 run.
    # Repairs broken [SRC: url] citations by searching the source domain and
    # verifying the replacement with the cross-provider verifier LLM.
    # Results are joined after Phase 3 and re-streamed if any URLs were fixed.
    import threading as _threading
    _repair_result: dict = {"text": sector_brief}
    _repair_thread = None
    if citations_enabled and '[SRC:' in sector_brief:
        from verification import repair_sector_brief_citations as _repair_fn
        def _run_repair():
            try:
                repaired, _ = _repair_fn(sector_brief, settings, log_fn=log_fn)
                _repair_result["text"] = repaired
            except Exception as _e:
                _log(f"Citation repair failed: {_e}")
        _repair_thread = _threading.Thread(target=_run_repair, daemon=True)
        _repair_thread.start()

    _log("=== Phase 2: Conferences ===")
    conferences_context = ""
    try:
        conferences, conferences_context = generate_conferences(thesis, sector_brief, log_fn=log_fn, extra_context=source_context, settings=settings)
        conferences = [c for c in conferences if isinstance(c, dict)]
    except (ValueError, json.JSONDecodeError) as e:
        _log(f"ERROR: Conference generation failed — {e}")
        conferences = []
    conferences_meta = _get_last_llm_meta()
    if phase_fn:
        phase_fn("conferences", {"conferences": conferences})

    _log("=== Phase 3: Company Universe ===")
    companies_context = ""
    try:
        companies, companies_context = generate_companies(thesis, sector_brief, log_fn=log_fn, extra_context=source_context, settings=settings)
        companies = [c for c in companies if isinstance(c, dict)]
        companies.sort(key=lambda c: c.get("fit_score", 0), reverse=True)
    except (ValueError, json.JSONDecodeError) as e:
        _log(f"ERROR: Company generation failed — {e}")
        companies = []
    companies_meta = _get_last_llm_meta()
    if phase_fn:
        phase_fn("companies", {"companies": companies})

    # Registry enrichment pass — overwrites LLM-inferred fields with authoritative data
    _log("=== Applying registry overrides ===")
    try:
        companies = _apply_registry_overrides(companies, settings, log_fn=log_fn)
    except Exception as e:
        _log(f"WARNING: Registry override pass failed — {e}")

    # Join citation repair (it ran in parallel with Phases 2 & 3).
    # If any URLs were fixed, re-stream the updated sector brief so the
    # frontend replaces the one with broken links.
    if _repair_thread is not None:
        _repair_thread.join(timeout=90)   # cap wait at 90s
        repaired_brief = _repair_result["text"]
        if repaired_brief != sector_brief:
            sector_brief = repaired_brief
            _log("Citation repair: re-streaming sector brief with repaired URLs")
            if phase_fn:
                phase_fn("sector_brief", {"sector_brief": sector_brief})

    _log("=== Research complete ===")
    raw_result = {
        "sector_brief": sector_brief,
        "conferences": conferences,
        "companies": companies,
    }

    # Verification pass
    verification_enabled = settings.get("verification_enabled", True)
    if verification_enabled:
        from verification import verify_research, _wrap_unverified
        try:
            result = verify_research(
                raw_result,
                settings=settings,
                log_fn=log_fn,
                companies_context=companies_context,
                conferences_context=conferences_context,
            )
        except Exception as e:
            _log(f"WARNING: Verification pass failed — {e}. Returning unverified result.")
            from verification import _wrap_unverified
            result = _wrap_unverified(raw_result)
    else:
        from verification import _wrap_unverified
        result = _wrap_unverified(raw_result)

    verification_meta = _get_last_llm_meta()
    result["_llm_meta"] = {
        "sector_brief": sector_brief_meta,
        "conferences": conferences_meta,
        "companies": companies_meta,
        "verification": verification_meta,
    }
    return result
