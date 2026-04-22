"""
verification.py — Post-generation AI evaluation & verification pass for DealScout.

Two layers:
  1. Citation extraction: parses [SRC: ...] markers from LLM output (free)
  2. AI re-verification: one search + one LLM call per entity (batch approach)

Gated by env flags:
  VERIFICATION_TAVILY_ENABLED    — set false to skip search verification (saves credits)
  VERIFICATION_CITATIONS_ENABLED — set false to skip citation prompts (free)
  VERIFICATION_TAVILY_MAX_CALLS  — hard call cap per run (0 = unlimited, default 20)
  VERIFIER_GOOGLE_MODEL          — Gemini model used for verification (default gemini-2.5-pro).
                                   Must differ from GOOGLE_MODEL (generator) to avoid
                                   self-verification bias.
"""

import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TAVILY_ENABLED = os.getenv("VERIFICATION_TAVILY_ENABLED", "true").lower() in ("1", "true", "yes")
CITATIONS_ENABLED = os.getenv("VERIFICATION_CITATIONS_ENABLED", "true").lower() in ("1", "true", "yes")
TAVILY_MAX_CALLS = int(os.getenv("VERIFICATION_TAVILY_MAX_CALLS", "20"))
CITATION_FETCH_MAX_CHARS = int(os.getenv("CITATION_FETCH_MAX_CHARS", "3000"))

# Verifier model — intentionally a DIFFERENT PROVIDER from the generator.
# When Gemini generates, OpenRouter verifies (cross-provider = strongest independence).
# When OpenRouter generates, Gemini verifies (VERIFIER_GOOGLE_MODEL, if key is set).
VERIFIER_OPENROUTER_MODEL = os.getenv("VERIFIER_OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
VERIFIER_GOOGLE_MODEL = os.getenv("VERIFIER_GOOGLE_MODEL", "gemini-2.5-flash")

CITATION_RE = re.compile(r'\[SRC:\s*([^\]]+)\]')


# ---------------------------------------------------------------------------
# Verifier LLM — opposite provider from the generator
# ---------------------------------------------------------------------------

def _call_verifier_llm(prompt: str, max_tokens: int, use_search: bool = False) -> str:
    """
    Fact-checker LLM — always a different provider from the data generator.

    When Gemini is the generator (GOOGLE_API_KEY set):
      → verifier uses OpenRouter (VERIFIER_OPENROUTER_MODEL, free Llama by default).
        Cross-provider independence: Llama cannot verify its own Gemini-generated output.
        Note: use_search is passed but free OpenRouter models may ignore it gracefully.
      → Degrades to same-provider Gemini only if OpenRouter is unavailable.

    When OpenRouter is the generator (no GOOGLE_API_KEY):
      → verifier uses Gemini (VERIFIER_GOOGLE_MODEL) with native search grounding.
      → Falls back to OpenRouter if Gemini is unavailable.
    """
    from research import _call_google, _call_openrouter, _google_available

    if _google_available():
        # Generator is Gemini → use OpenRouter for cross-provider verification
        try:
            return _call_openrouter(VERIFIER_OPENROUTER_MODEL, prompt, max_tokens, use_web_search=use_search)
        except Exception as e:
            logger.warning(
                "Verifier OpenRouter (%s) unavailable: %s — degrading to same-provider Gemini verification",
                VERIFIER_OPENROUTER_MODEL, e,
            )
            # Graceful degrade: same provider but still an independent prompt evaluation
            generator_model = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
            return _call_google(prompt, max_tokens, use_search=use_search, settings={"google_model": generator_model})
    else:
        # Generator is OpenRouter → use Gemini for cross-provider verification
        try:
            return _call_google(
                prompt, max_tokens,
                use_search=use_search,
                settings={"google_model": VERIFIER_GOOGLE_MODEL},
            )
        except Exception as e:
            logger.warning("Verifier Gemini (%s) failed: %s — falling back to OpenRouter", VERIFIER_GOOGLE_MODEL, e)
            return _call_openrouter(VERIFIER_OPENROUTER_MODEL, prompt, max_tokens, use_web_search=use_search)


def _verifier_uses_gemini_search() -> bool:
    """True when the verifier will call Gemini with native search grounding."""
    from research import _google_available
    # Gemini search is only used when OpenRouter is the generator (so Gemini is the verifier)
    return not _google_available()

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Citation extraction (free — no network calls)
# ---------------------------------------------------------------------------

def _extract_citations(text: str):
    """
    Extract all [SRC: ...] markers from text.
    Returns (cleaned_text, citations_list).

    Each citation dict:
        claim_snippet  — text immediately before the marker (up to 80 chars)
        citation_raw   — raw content of [SRC: ...]
        citation_type  — "url" | "training_knowledge" | "estimated" | "derived"
        citation_url   — https://... or None
    """
    citations = []
    idx_counter = [0]

    def _handle_match(m):
        source = m.group(1).strip()
        start = max(0, m.start() - 100)
        preceding = text[start:m.start()].strip()
        snippet = preceding
        for sep in ('. ', '! ', '? ', '\n'):
            pos = snippet.rfind(sep)
            if pos >= 0:
                snippet = snippet[pos + len(sep):]
        claim_snippet = snippet[:80].strip() or f"claim_{idx_counter[0]}"
        idx_counter[0] += 1

        src_lower = source.lower()
        if src_lower == 'estimated':
            ctype, curl = 'estimated', None
        elif src_lower == 'derived':
            ctype, curl = 'derived', None
        elif src_lower in ('training_knowledge', 'model_inference'):
            ctype, curl = 'training_knowledge', None
        elif source.startswith('http://') or source.startswith('https://'):
            ctype, curl = 'url', source
        else:
            ctype, curl = 'training_knowledge', None

        citations.append({
            'claim_snippet': claim_snippet,
            'citation_raw': source,
            'citation_type': ctype,
            'citation_url': curl,
        })
        return ''

    cleaned = CITATION_RE.sub(_handle_match, text)
    return cleaned.strip(), citations


def _clean_entity_fields(entity: dict) -> dict:
    """Strip [SRC: ...] markers from entity string field values and drop internal _ keys."""
    return {
        k: CITATION_RE.sub('', str(v)).strip() if isinstance(v, str) else v
        for k, v in entity.items()
        if not k.startswith('_')  # drop internal metadata keys like _grounding_url
    }


def _extract_field_citation(field_value: str):
    """
    Extract a single [SRC: ...] from a structured field value.
    Returns (clean_value, citation_type, citation_url).
    """
    m = CITATION_RE.search(str(field_value))
    if not m:
        return str(field_value), 'training_knowledge', None
    source = m.group(1).strip()
    clean_value = CITATION_RE.sub('', str(field_value)).strip()
    src_lower = source.lower()
    if src_lower == 'estimated':
        return clean_value, 'estimated', None
    elif src_lower == 'derived':
        return clean_value, 'derived', None
    elif src_lower in ('training_knowledge', 'model_inference'):
        return clean_value, 'training_knowledge', None
    elif source.startswith('http://') or source.startswith('https://'):
        return clean_value, 'url', source
    return clean_value, 'training_knowledge', None


def _validate_citation_url(url: str) -> bool:
    """HEAD request to confirm URL exists. Returns True if status < 400."""
    try:
        r = httpx.head(url, timeout=5, follow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Website discovery (Tavily search when URL is missing)
# ---------------------------------------------------------------------------

def _find_website(name: str, location: str = "", log_fn=None, is_conference: bool = False, search_provider: str = "duckduckgo") -> Optional[str]:
    """
    Search for the official website of a company or conference when none is known.
    Returns the first plausible homepage URL or None.
    """
    from search import run_search

    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    try:
        if is_conference:
            query = f'"{name}" conference official website'
        else:
            query = f'"{name}" {location} official website homepage'.strip()
        results = run_search(query, provider=search_provider)
        for r in results:
            url = r.get('url', '')
            # Accept the first result that looks like a homepage (short path, right domain)
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                path = parsed.path.rstrip('/')
                # Prefer root or very short paths — likely a homepage
                if parsed.scheme in ('http', 'https') and len(path) <= 20:
                    _log(f"  _find_website: found {url} for '{name}'")
                    return url
            except Exception:
                continue
        # Fallback: return first result URL if any
        if results:
            return results[0].get('url')
    except Exception as e:
        _log(f"  _find_website failed for '{name}': {e}")
    return None


# ---------------------------------------------------------------------------
# Website liveness check (free HEAD request — no Tavily)
# ---------------------------------------------------------------------------

def _check_website_live(url: str, log_fn=None) -> dict:
    """
    HEAD-check a company website. Detects broken URLs and domain redirects
    that may indicate a rebrand (e.g. CargoApps → impargo.com).

    If the full path fails (e.g. soloplan.com/en returns 404), automatically
    retries the root domain (soloplan.com) before marking as broken.
    """
    def _log(msg):
        if log_fn:
            log_fn(msg)

    if not url:
        return {'status': 'unverifiable', 'citation_note': 'No website URL provided'}

    def _head(target: str):
        return httpx.head(target, timeout=8, follow_redirects=True)

    def _extract_domain(u: str) -> str:
        return u.split('/')[2].lstrip('www.') if '//' in u else ''

    def _root_url(u: str) -> Optional[str]:
        """Return scheme+domain only, or None if already at root."""
        try:
            parts = u.split('/')
            # parts: ['https:', '', 'domain.com', 'path', ...]
            if len(parts) <= 3 or (len(parts) == 4 and parts[3] == ''):
                return None  # already at root
            return f"{parts[0]}//{parts[2]}"
        except Exception:
            return None

    try:
        resp = _head(url)
        final_url = str(resp.url)
        original_domain = _extract_domain(url)
        final_domain = _extract_domain(final_url)

        if resp.status_code < 400:
            if original_domain and final_domain and original_domain != final_domain:
                return {
                    'status': 'inferred',
                    'source_url': final_url,
                    'source_snippet': f'Website redirects to {final_domain} — possible rebrand or domain change',
                    'citation_note': f'Original URL {url} now points to {final_url}',
                }
            return {'status': 'verified', 'source_url': final_url, 'source_snippet': 'Website is live and reachable'}

        # Sub-path failed — retry root domain before giving up
        root = _root_url(url)
        if root:
            _log(f"    {url} returned {resp.status_code} — retrying root: {root}")
            try:
                root_resp = _head(root)
                root_final = str(root_resp.url)
                root_domain = _extract_domain(root_final)
                if root_resp.status_code < 400:
                    return {
                        'status': 'verified',
                        'source_url': root_final,
                        'source_snippet': f'Website live at {root_domain} (sub-path {url} returned {resp.status_code})',
                    }
            except Exception:
                pass

        return {
            'status': 'contradicted',
            'citation_note': f'Website returned HTTP {resp.status_code} — may be broken or company no longer exists',
        }

    except Exception as e:
        return {'status': 'unverifiable', 'citation_note': f'Could not reach website: {type(e).__name__}'}


# ---------------------------------------------------------------------------
# Citation URL fetcher + secondary verification
# ---------------------------------------------------------------------------

def _fetch_and_verify_citation(
    url: str,
    claim: str,
    entity_name: str,
    log_fn=None,
) -> dict:
    """
    Fetch the cited URL, extract readable text, ask a second LLM call to
    confirm whether the claim is actually supported by the page content.
    Returns a Verification-compatible dict with citation_url and source_url set.

    When the URL is unreachable (404, redirect-to-homepage, HTTP error) and
    Gemini is the verifier, falls back to a targeted site: search on the domain
    before marking the claim unverifiable.
    """
    from research import _strip_json_fences
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse as _urlparse

    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    def _site_search_fallback(reason: str) -> dict:
        """
        When a cited URL is broken, try site:domain search via Gemini to find
        the content at a different path. Only runs when Gemini is the verifier.
        """
        if not _verifier_uses_gemini_search():
            return {
                'status': 'unverifiable',
                'citation_url': url,
                'source_url': url,
                'citation_note': reason,
                'claim': claim,
            }
        try:
            domain = _urlparse(url).netloc or url
            _log(f"  {reason} — trying site:{domain} search for claim")
            prompt = f"""A citation URL returned an error ({reason}), but the domain may still host the content at a different path.

Claim to verify: "{claim}"
About: {entity_name}
Original URL (broken): {url}
Domain: {domain}

Search site:{domain} to find whether this claim is supported anywhere on that site.

Return ONLY a JSON object:
{{
  "verdict": "verified" | "contradicted" | "unverifiable",
  "source_url": "URL where the content was found, or null",
  "supporting_excerpt": "brief quote supporting your verdict, or null"
}}"""
            raw = _call_verifier_llm(prompt, max_tokens=300, use_search=True)
            from research import _strip_json_fences as _sfences
            _cleaned = _sfences(raw)
            try:
                parsed = json.loads(_cleaned)
            except json.JSONDecodeError:
                from json_repair import repair_json
                parsed = repair_json(_cleaned, return_objects=True)
                if not isinstance(parsed, dict):
                    raise ValueError(f"json_repair returned non-dict for site search: {type(parsed)}")
            verdict = parsed.get('verdict', 'unverifiable')
            if verdict not in ('verified', 'contradicted', 'unverifiable'):
                verdict = 'unverifiable'
            found_url = parsed.get('source_url')
            _log(f"  Site search result: {verdict}" + (f" — {found_url}" if found_url else ""))
            return {
                'status': verdict,
                'citation_url': url,
                'source_url': found_url or url,
                'source_snippet': parsed.get('supporting_excerpt'),
                'citation_note': f'Original URL broken ({reason}); verified via site search' if verdict != 'unverifiable' else reason,
                'claim': claim,
            }
        except Exception as e:
            _log(f"  Site search fallback failed: {e}")
            return {
                'status': 'unverifiable',
                'citation_url': url,
                'source_url': url,
                'citation_note': reason,
                'claim': claim,
            }

    # Sub-step A: fetch page
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True,
                         headers={"User-Agent": _BROWSER_UA})
        final_url = str(resp.url)
        if resp.status_code == 404:
            _log(f"  Citation URL 404: {url}")
            return _site_search_fallback('Cited URL returned 404')
        if resp.status_code >= 400:
            return _site_search_fallback(f'Could not fetch cited URL: HTTP {resp.status_code}')

        # Detect homepage-redirect: original URL had a specific path but resolved
        # to the root — the specific page doesn't exist (hallucinated URL pattern)
        try:
            orig = _urlparse(url)
            final = _urlparse(final_url)
            orig_path = orig.path.rstrip('/')
            final_path = final.path.rstrip('/')
            orig_domain = orig.netloc.lower().lstrip('www.')
            final_domain = final.netloc.lower().lstrip('www.')
            # Same domain but original had a deep path that collapsed to root/homepage
            if (orig_path and orig_path != '/'
                    and (final_path in ('', '/') or final_path == orig_path[:3])
                    and orig_domain == final_domain):
                _log(f"  Citation URL redirects to homepage — likely hallucinated: {url} → {final_url}")
                return _site_search_fallback('Cited URL redirects to homepage — specific page does not exist')
        except Exception:
            pass

    except httpx.TimeoutException:
        return {
            'status': 'unverifiable',
            'citation_url': url,
            'source_url': url,
            'citation_note': 'Could not fetch cited URL: timeout',
            'claim': claim,
        }
    except Exception as e:
        return {
            'status': 'unverifiable',
            'citation_url': url,
            'source_url': url,
            'citation_note': f'Could not fetch cited URL: {type(e).__name__}',
            'claim': claim,
        }

    # Sub-step B: extract readable text (same logic as scraper.py)
    page_text = ""
    try:
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        content = (
            soup.find("article") or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find(class_="content") or soup.find(id="content")
            or soup.body
        )
        if content:
            raw = content.get_text(separator=" ", strip=True)
            page_text = re.sub(r"\s{2,}", " ", raw)[:CITATION_FETCH_MAX_CHARS]
    except Exception:
        pass

    if not page_text:
        return {
            'status': 'unverifiable',
            'citation_url': url,
            'source_url': final_url,
            'citation_note': 'Cited URL fetched but no readable content found',
            'claim': claim,
        }

    # Sub-step C: secondary LLM verification call (verifier model — not the generator)
    try:
        prompt = f"""You are a fact-checker reading a web page to verify a specific claim.

Claim to verify: "{claim}"
About: {entity_name}

Web page content (from {final_url}):
{page_text}

Does this page content support, contradict, or not address the claim?

Return ONLY a JSON object:
{{
  "verdict": "verified" | "contradicted" | "unverifiable",
  "supporting_excerpt": "direct quote from the page supporting your verdict, max 100 chars, or null",
  "corrected_value": "if contradicted, the correct value from the page, or null"
}}"""

        raw = _call_verifier_llm(prompt, max_tokens=300)
        _cleaned = _strip_json_fences(raw)
        try:
            parsed = json.loads(_cleaned)
        except json.JSONDecodeError:
            from json_repair import repair_json
            parsed = repair_json(_cleaned, return_objects=True)
            if not isinstance(parsed, dict):
                raise ValueError(f"json_repair returned non-dict for citation verify: {type(parsed)}")
        verdict = parsed.get('verdict', 'unverifiable')
        if verdict not in ('verified', 'contradicted', 'unverifiable'):
            verdict = 'unverifiable'

        _log(f"  Citation verify: {verdict} — {final_url}")
        return {
            'status': verdict,
            'citation_url': url,
            'source_url': final_url,
            'source_snippet': parsed.get('supporting_excerpt'),
            'corrected_value': parsed.get('corrected_value') if verdict == 'contradicted' else None,
            'claim': claim,
        }
    except Exception as e:
        _log(f"  Secondary LLM call failed: {e}")
        return {
            'status': 'unverifiable',
            'citation_url': url,
            'source_url': final_url,
            'citation_note': f'Verification call failed: {type(e).__name__}',
            'claim': claim,
        }


def _verify_field_with_citations(
    field_name: str,
    claim: str,
    citation_url: Optional[str],
    citation_type: str,
    entity_name: str,
    log_fn=None,
    use_tavily: Optional[bool] = None,
    existing_context: str = "",
    call_state: Optional[dict] = None,
    search_provider: str = "duckduckgo",
) -> dict:
    """
    Citation-first priority logic:
      estimated / derived    → inferred immediately, no network calls
      training_knowledge     → Tavily fallback (if budget allows)
      url                    → fetch + verify; Tavily fallback if fetch fails
    """
    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    enabled = TAVILY_ENABLED if use_tavily is None else use_tavily

    if citation_type in ('estimated', 'derived'):
        _log(f"  {field_name}: {citation_type} → inferred immediately")
        return {'status': 'inferred', 'claim': claim, 'citation_note': citation_type}

    # DuckDuckGo is free — no cap. Cap only applies to Tavily.
    under_cap = (
        search_provider != 'tavily'
        or TAVILY_MAX_CALLS == 0
        or call_state is None
        or call_state.get('count', 0) < TAVILY_MAX_CALLS
    )
    budget_ok = enabled and under_cap

    if citation_type == 'training_knowledge':
        if budget_ok:
            _log(f"  {field_name}: training_knowledge → search fallback")
            batch = _verify_entity_batch(
                entity_name=entity_name,
                search_query=f'"{entity_name}" {claim[:60]}',
                claims={field_name: claim},
                log_fn=log_fn,
                use_tavily=True,
                existing_context=existing_context,
                call_state=call_state,
                search_provider=search_provider,
            )
            return batch.get(field_name, {'status': 'unverifiable', 'claim': claim})
        return {
            'status': 'unverifiable',
            'citation_note': 'From model training knowledge — no source available',
            'claim': claim,
        }

    if citation_type == 'url' and citation_url:
        result = _fetch_and_verify_citation(citation_url, claim, entity_name, log_fn=log_fn)
        if result.get('status') == 'unverifiable' and budget_ok:
            _log(f"  {field_name}: citation fetch failed → search fallback")
            batch = _verify_entity_batch(
                entity_name=entity_name,
                search_query=f'"{entity_name}" {claim[:60]}',
                claims={field_name: claim},
                log_fn=log_fn,
                use_tavily=True,
                existing_context=existing_context,
                call_state=call_state,
                search_provider=search_provider,
            )
            return batch.get(field_name, result)
        return result

    return {'status': 'pending', 'claim': claim}


# ---------------------------------------------------------------------------
# Batch entity verification (1 Tavily call + 1 LLM call per entity)
# ---------------------------------------------------------------------------

def _verify_entity_batch(
    entity_name: str,
    search_query: str,
    claims: dict,           # {field_name: claim_string}
    log_fn=None,
    use_tavily: Optional[bool] = None,
    existing_context: str = "",
    call_state: Optional[dict] = None,  # {"count": int} — shared mutable counter
    search_provider: str = "duckduckgo",
    grounding_url: str = None,          # Gemini grounding URL for this entity (replaces search)
) -> dict:
    """
    Verify all claims for one entity using the verifier model (not the generator).
    - Path A: existing_context cache hit → verifier LLM only (free)
    - Path B: Gemini available → verifier with native search (no Tavily/DDG)
    - Path C: no Gemini → run_search + verifier LLM (Tavily/DuckDuckGo fallback)
    Returns {field_name: Verification-compatible dict}.
    """
    from search import run_search
    from research import _strip_json_fences

    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    enabled = TAVILY_ENABLED if use_tavily is None else use_tavily

    if not enabled:
        return {k: {'status': 'pending', 'claim': v} for k, v in claims.items()}

    # Check call cap — only applies to Tavily (paid); DuckDuckGo is free, no cap needed
    _cs_lock = call_state.get('_lock') if call_state else None
    if search_provider == 'tavily' and call_state is not None and TAVILY_MAX_CALLS > 0:
        with (_cs_lock or threading.Lock()):
            if call_state.get('count', 0) >= TAVILY_MAX_CALLS:
                _log(f"  Tavily cap reached ({TAVILY_MAX_CALLS}) — skipping {entity_name}")
                return {k: {'status': 'pending', 'citation_note': 'Tavily call limit reached for this run', 'claim': v} for k, v in claims.items()}

    claims_json = json.dumps(claims, indent=2)
    tavily_context = ""
    used_cache = False

    # --- Path A0: use Gemini grounding URL fetched during generation (free — no new search) ---
    if grounding_url:
        try:
            _log(f"  Using grounding URL for {entity_name}: {grounding_url[:80]}")
            r = httpx.get(grounding_url, timeout=8, follow_redirects=True,
                          headers={"User-Agent": _BROWSER_UA})
            if r.status_code < 400:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                    tag.decompose()
                page_text = ' '.join(soup.get_text(separator=' ').split())[:3000]
                if page_text:
                    tavily_context = page_text
                    used_cache = True
                    _log(f"  Grounding URL fetched ({len(page_text)} chars) — using as verification context")
        except Exception as e:
            _log(f"  Grounding URL fetch failed: {e} — falling through to search")

    # --- Path A: reuse existing context (free — no search call) ---
    if not used_cache and existing_context and entity_name.lower() in existing_context.lower():
        tavily_context = existing_context[:3000]
        used_cache = True
        _log(f"  Using cached research context for {entity_name}")

    # Paths A0 + A share the same context-based prompt
    if used_cache:
        prompt = f"""You are a fact-checker. Given these web search results about {entity_name}, assess each claim below as "verified", "contradicted", or "unverifiable".

Search results:
{tavily_context}

Claims to assess:
{claims_json}

Return ONLY a JSON object where each key matches a claim key and the value is:
{{
  "verdict": "verified" | "contradicted" | "inferred" | "unverifiable",
  "source_url": "most relevant URL or null",
  "snippet": "brief supporting excerpt or null",
  "corrected_value": "the correct scalar value from sources if contradicted (e.g. '2008', 'Acquired by SAP in 2021', 'October 14-16, 2026'), or null if not contradicted"
}}

verdict must be exactly one of: "verified", "contradicted", "inferred", "unverifiable".
"inferred" is the DEFAULT when a claim is plausible given what you know about this entity — use it whenever you can say "this is probably correct" even without an explicit source in the excerpts.
"unverifiable" should be rare — use it only when you have no basis whatsoever to judge the claim (e.g. no information about this entity at all).
"verified" requires an explicit confirmation in the excerpts.
"contradicted" requires a clear conflict with the excerpts.
corrected_value should be short and direct — it will be displayed inline as a replacement."""
        try:
            raw = _call_verifier_llm(prompt, max_tokens=400, use_search=False)
        except Exception as e:
            _log(f"  Verifier LLM (context path) failed: {e}")
            return {k: {'status': 'unverifiable', 'checked_query': None} for k in claims}

    # --- Path B: Gemini native search (only when Gemini is the verifier) ---
    elif _verifier_uses_gemini_search():
        if call_state is not None:
            with (_cs_lock or threading.Lock()):
                call_state['count'] = call_state.get('count', 0) + 1
        _log(f"  Verifier search #{call_state.get('count', '?') if call_state else '?'} (Gemini native): {search_query}")
        prompt = f"""You are a fact-checker. Use web search to find information about {entity_name} and verify the following claims.

Search for: {search_query}

Claims to assess:
{claims_json}

For each claim, search for relevant information, then assess as "verified", "contradicted", or "unverifiable".

Return ONLY a JSON object where each key matches a claim key and the value is:
{{
  "verdict": "verified" | "contradicted" | "inferred" | "unverifiable",
  "source_url": "most relevant URL or null",
  "snippet": "brief supporting excerpt or null",
  "corrected_value": "the correct scalar value from sources if contradicted (e.g. '2008', 'Acquired by SAP in 2021', 'October 14-16, 2026'), or null if not contradicted"
}}

verdict must be exactly one of: "verified", "contradicted", "inferred", "unverifiable".
"inferred" is the DEFAULT when a claim is plausible given what you know about this entity — use it whenever you can say "this is probably correct" even without an explicit source in the excerpts.
"unverifiable" should be rare — use it only when you have no basis whatsoever to judge the claim (e.g. no information about this entity at all).
"verified" requires an explicit confirmation in the excerpts.
"contradicted" requires a clear conflict with the excerpts.
corrected_value should be short and direct — it will be displayed inline as a replacement."""
        try:
            raw = _call_verifier_llm(prompt, max_tokens=400, use_search=True)
        except Exception as e:
            _log(f"  Verifier LLM (Gemini search) failed: {e}")
            return {k: {'status': 'unverifiable', 'checked_query': search_query} for k in claims}

    # --- Path C: fallback — run_search + verifier LLM (no Gemini available) ---
    else:
        try:
            results = run_search(search_query, provider=search_provider)
            # Only track call count for Tavily (paid); DuckDuckGo is free
            if search_provider == 'tavily' and call_state is not None:
                with (_cs_lock or threading.Lock()):
                    call_state['count'] = call_state.get('count', 0) + 1
            if results:
                ctx_parts = [f"URL: {r.get('url', '')}\n{r.get('content', '')[:400]}" for r in results[:5]]
                tavily_context = "\n\n".join(ctx_parts)
            else:
                tavily_context = ""
            count_str = f" #{call_state['count']}" if search_provider == 'tavily' and call_state else ""
            _log(f"  {search_provider} search{count_str}: {search_query}")
        except Exception as e:
            _log(f"  Search failed: {e}")
            return {k: {'status': 'unverifiable', 'checked_query': search_query} for k in claims}

        if not tavily_context:
            return {k: {'status': 'unverifiable', 'checked_query': search_query} for k in claims}

        prompt = f"""You are a fact-checker. Given these web search results about {entity_name}, assess each claim below as "verified", "contradicted", or "unverifiable".

Search results:
{tavily_context}

Claims to assess:
{claims_json}

Return ONLY a JSON object where each key matches a claim key and the value is:
{{
  "verdict": "verified" | "contradicted" | "inferred" | "unverifiable",
  "source_url": "most relevant URL or null",
  "snippet": "brief supporting excerpt or null",
  "corrected_value": "the correct scalar value from sources if contradicted (e.g. '2008', 'Acquired by SAP in 2021', 'October 14-16, 2026'), or null if not contradicted"
}}

verdict must be exactly one of: "verified", "contradicted", "inferred", "unverifiable".
"inferred" is the DEFAULT when a claim is plausible given what you know about this entity — use it whenever you can say "this is probably correct" even without an explicit source in the excerpts.
"unverifiable" should be rare — use it only when you have no basis whatsoever to judge the claim (e.g. no information about this entity at all).
"verified" requires an explicit confirmation in the excerpts.
"contradicted" requires a clear conflict with the excerpts.
corrected_value should be short and direct — it will be displayed inline as a replacement."""
        try:
            raw = _call_verifier_llm(prompt, max_tokens=400, use_search=False)
        except Exception as e:
            _log(f"  Verifier LLM (search fallback) failed: {e}")
            return {k: {'status': 'unverifiable', 'checked_query': search_query, 'claim': v} for k, v in claims.items()}

    # Parse verifier output (all paths converge here)
    try:
        raw = _strip_json_fences(raw)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            from json_repair import repair_json
            parsed = repair_json(raw, return_objects=True)
            if not isinstance(parsed, dict):
                raise ValueError(f"json_repair returned non-dict for batch verify: {type(parsed)}")

        results_out = {}
        for field, claim_text in claims.items():
            field_result = parsed.get(field, {})
            verdict = field_result.get('verdict', 'unverifiable')
            if verdict not in ('verified', 'contradicted', 'inferred', 'unverifiable'):
                verdict = 'unverifiable'
            corrected = field_result.get('corrected_value') if verdict == 'contradicted' else None
            results_out[field] = {
                'status': verdict,
                'source_url': field_result.get('source_url'),
                'source_snippet': field_result.get('snippet'),
                'checked_query': None if used_cache else search_query,
                'claim': claim_text,
                'corrected_value': corrected,
            }
        return results_out
    except Exception as e:
        _log(f"  Batch LLM call failed: {e}")
        return {k: {'status': 'unverifiable', 'checked_query': search_query, 'claim': v} for k, v in claims.items()}


# ---------------------------------------------------------------------------
# Company verification
# ---------------------------------------------------------------------------

def verify_company(
    company: dict,
    log_fn=None,
    use_tavily: Optional[bool] = None,
    existing_context: str = "",
    call_state: Optional[dict] = None,
    search_provider: str = "duckduckgo",
) -> dict:
    """
    Verify 3 high-stakes fields + website liveness check.
    Returns a VerifiedCompany-compatible dict.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    name = company.get('name', '?')
    country = company.get('country', '')
    _log(f"> Verifying: {name} ({country})")

    verifications = {}

    # Website: check if live; if missing, search for it
    if company.get('website'):
        wv = _check_website_live(company['website'], log_fn=log_fn)
        verifications['website'] = wv
        snippet = wv.get('source_snippet') or wv.get('citation_note', '')
        _log(f"    website: {wv['status']} — {snippet[:80]}")
    else:
        found_url = _find_website(name, country, log_fn=log_fn, search_provider=search_provider)
        if found_url:
            company['website'] = found_url
            verifications['website'] = {'status': 'verified', 'source_url': found_url,
                                        'source_snippet': f'Website found via search: {found_url}'}
            _log(f"    website: found via search → {found_url}")

    # ARR and headcount: always inferred — private company data is rarely public
    # Extract citations from raw values for claim text, but still mark inferred
    raw_arr = str(company.get('estimated_arr') or '')
    if raw_arr and raw_arr != 'None':
        clean_arr, _, _ = _extract_field_citation(raw_arr)
        verifications['estimated_arr'] = {
            'status': 'inferred',
            'source_snippet': 'ARR estimates for private companies are rarely publicly available — treat as model inference',
            'claim': f'{name} has estimated ARR of {clean_arr}',
        }

    raw_emp = str(company.get('employee_count') or '')
    if raw_emp and raw_emp != 'None':
        clean_emp, _, _ = _extract_field_citation(raw_emp)
        verifications['employee_count'] = {
            'status': 'inferred',
            'source_snippet': 'Headcount estimates for private companies are rarely publicly available — treat as model inference',
            'claim': f'{name} has approximately {clean_emp} employees',
        }

    # For each verifiable field: extract citation first, use citation-first if URL available
    batch_claims = {}

    # existence: no inline citation expected — always Tavily batch
    batch_claims['existence'] = f'{name} is a software company based in {country}'

    # ownership: citation-first if URL provided by LLM
    raw_ownership = str(company.get('ownership') or '')
    if raw_ownership and raw_ownership != 'None':
        clean_ownership, ctype, curl = _extract_field_citation(raw_ownership)
        claim = f'{name} ownership: {clean_ownership}'
        if ctype == 'url' and curl:
            _log(f"    ownership: citation URL found → fetching {curl}")
            verifications['ownership'] = _verify_field_with_citations(
                'ownership', claim, curl, ctype, name, log_fn, use_tavily, existing_context, call_state, search_provider)
            icon = '✓' if verifications['ownership'].get('status') == 'verified' else '~'
            _log(f"    ownership: {verifications['ownership'].get('status')} {icon}")
        else:
            batch_claims['ownership'] = claim

    # founded: citation-first if URL provided by LLM
    raw_founded = str(company.get('founded') or '')
    if raw_founded and raw_founded != 'None':
        clean_founded, ctype, curl = _extract_field_citation(raw_founded)
        claim = f'{name} was founded in {clean_founded}'
        if ctype == 'url' and curl:
            _log(f"    founded: citation URL found → fetching {curl}")
            verifications['founded'] = _verify_field_with_citations(
                'founded', claim, curl, ctype, name, log_fn, use_tavily, existing_context, call_state, search_provider)
            icon = '✓' if verifications['founded'].get('status') == 'verified' else '~'
            _log(f"    founded: {verifications['founded'].get('status')} {icon}")
        else:
            batch_claims['founded'] = claim

    # Clean company for output — strip all [SRC: ...] markers AFTER citation extraction
    company = _clean_entity_fields(company)

    # Batch remaining fields
    # Prefer grounding URL from generation; fall back to the company's own website
    # (the About/homepage typically contains ownership, founding year, team info)
    entity_grounding_url = company.get('_grounding_url') or company.get('website')
    if batch_claims:
        search_query = f'"{name}" {country} software company'
        batch = _verify_entity_batch(
            entity_name=name,
            search_query=search_query,
            claims=batch_claims,
            log_fn=log_fn,
            use_tavily=use_tavily,
            existing_context=existing_context,
            call_state=call_state,
            search_provider=search_provider,
            grounding_url=entity_grounding_url,
        )
        for field, v in batch.items():
            verifications[field] = v
            icon = '✓' if v['status'] == 'verified' else ('✗' if v['status'] == 'contradicted' else '~')
            _log(f"    {field}: {v['status']} {icon}")

    overall = _derive_confidence(verifications)
    _log(f"    Overall confidence: {overall}")
    return {
        'company': company,
        'verifications': verifications,
        'overall_confidence': overall,
    }


# ---------------------------------------------------------------------------
# Conference website scrape — extract/verify date & location from the page
# ---------------------------------------------------------------------------

def _scrape_conference_date_location(
    url: str,
    name: str,
    expected_date: str,
    expected_location: str,
    log_fn=None,
) -> Optional[dict]:
    """
    Fetch the conference homepage and ask the verifier LLM to confirm or
    correct the date and location from the live page text.
    Returns a verification dict on success, None on any failure.
    """
    from bs4 import BeautifulSoup

    def _log(msg):
        if log_fn:
            log_fn(msg)

    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True, headers={"User-Agent": _BROWSER_UA})
        if resp.status_code >= 400:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        content = (
            soup.find("article") or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find(class_="content") or soup.find(id="content")
            or soup.body
        )
        if not content:
            return None
        raw = content.get_text(separator=" ", strip=True)
        page_text = re.sub(r"\s{2,}", " ", raw)[:CITATION_FETCH_MAX_CHARS]
        if len(page_text) < 50:
            return None

    except Exception as e:
        _log(f"    website scrape error: {e}")
        return None

    claim = f"{name} takes place on {expected_date} in {expected_location}"
    prompt = f"""You are verifying a conference's date and location from its official website.

Conference: {name}
Expected date: {expected_date}
Expected location: {expected_location}

Website text (first portion):
{page_text}

Find the actual date and location on this page.
Return ONLY a JSON object:
{{
  "verdict": "verified" | "contradicted" | "unverifiable",
  "actual_date": "date found on page, or null if not found",
  "actual_location": "city or venue found on page, or null if not found",
  "corrected_value": "corrected 'date · location' string if contradicted, null otherwise",
  "excerpt": "brief supporting quote from the page, max 80 chars, or null"
}}

verdict=verified: page confirms the expected date AND location.
verdict=contradicted: page shows a clearly different date or location.
verdict=unverifiable: date/location not clearly stated on the page."""

    try:
        raw_llm = _call_verifier_llm(prompt, max_tokens=200, use_search=False)
        from research import _strip_json_fences, _escape_control_chars
        cleaned = _escape_control_chars(_strip_json_fences(raw_llm))
        try:
            data = json.loads(cleaned)
        except Exception:
            from json_repair import repair_json
            data = repair_json(cleaned, return_objects=True)
            if not isinstance(data, dict):
                return None

        verdict = data.get("verdict", "unverifiable")
        if verdict not in ("verified", "contradicted", "unverifiable"):
            verdict = "unverifiable"

        result: dict = {"status": verdict, "source_url": url, "claim": claim}

        if verdict == "contradicted" and data.get("corrected_value"):
            result["corrected_value"] = data["corrected_value"]
            actual = f"{data.get('actual_date', '?')} · {data.get('actual_location', '?')}"
            result["source_snippet"] = data.get("excerpt") or f"Page shows: {actual}"
            result["citation_note"] = "Date/location differs from generated value — corrected from official website"
        elif verdict == "verified":
            result["source_snippet"] = data.get("excerpt") or "Confirmed on official website"
        else:
            result["citation_note"] = "Date/location not clearly stated on website homepage"

        return result

    except Exception as e:
        _log(f"    website scrape LLM error: {e}")
        return None


# ---------------------------------------------------------------------------
# Conference verification
# ---------------------------------------------------------------------------

def verify_conference(
    conference: dict,
    log_fn=None,
    use_tavily: Optional[bool] = None,
    existing_context: str = "",
    call_state: Optional[dict] = None,
    search_provider: str = "duckduckgo",
) -> dict:
    """
    Verify 2 high-stakes fields (date+location, existence).
    estimated_cost is marked inferred directly — rarely publicly listed.
    Returns a VerifiedConference-compatible dict.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    name = conference.get('name', '?')

    # Extract citations from date/location BEFORE cleaning
    raw_date = str(conference.get('date') or '')
    raw_location = str(conference.get('location') or '')
    clean_date, date_ctype, date_curl = _extract_field_citation(raw_date)
    clean_location, loc_ctype, loc_curl = _extract_field_citation(raw_location)
    # Pick the best available URL for date_location claim
    dl_citation_url = date_curl or loc_curl
    dl_citation_type = 'url' if dl_citation_url else 'training_knowledge'

    year_m = re.search(r'\d{4}', clean_date)
    year = year_m.group(0) if year_m else ''

    _log(f"> Verifying conference: {name}")

    verifications = {}

    # Website: check existing URL; search if missing or dead
    if conference.get('website'):
        live_status = _check_website_live(conference['website'])
        if live_status == 'contradicted':
            _log(f"    website: 404/dead → searching for replacement")
            found_url = _find_website(name, clean_location or '', log_fn=log_fn, is_conference=True, search_provider=search_provider)
            if found_url:
                conference['website'] = found_url
                _log(f"    website: replaced → {found_url}")
            else:
                conference['website'] = None
                _log(f"    website: no replacement found")
    else:
        found_url = _find_website(name, clean_location or '', log_fn=log_fn, is_conference=True, search_provider=search_provider)
        if found_url:
            conference['website'] = found_url
            _log(f"    website: found via search → {found_url}")

    # Mark cost as inferred — ticket prices are rarely searchable
    raw_cost = str(conference.get('estimated_cost') or '')
    if raw_cost and raw_cost != 'None':
        clean_cost, _, _ = _extract_field_citation(raw_cost)
        verifications['estimated_cost'] = {
            'status': 'inferred',
            'source_snippet': 'Conference ticket prices are rarely available in web search results — treat as estimate',
            'claim': f'Attendance costs {clean_cost}',
        }

    batch_claims = {}

    # date_location: try citation URL first, then scrape website, fall back to batch
    if clean_date or clean_location:
        dl_claim = f'{name} is taking place in {clean_date} in {clean_location}'
        if dl_citation_type == 'url' and dl_citation_url:
            _log(f"    date_location: citation URL found → fetching {dl_citation_url}")
            verifications['date_location'] = _verify_field_with_citations(
                'date_location', dl_claim, dl_citation_url, dl_citation_type,
                name, log_fn, use_tavily, existing_context, call_state, search_provider)
            icon = '✓' if verifications['date_location'].get('status') == 'verified' else '~'
            _log(f"    date_location: {verifications['date_location'].get('status')} {icon}")
        elif conference.get('website'):
            _log(f"    date_location: scraping website → {conference['website']}")
            scraped = _scrape_conference_date_location(
                conference['website'], name, clean_date, clean_location, log_fn=log_fn)
            if scraped and scraped.get('status') in ('verified', 'contradicted'):
                verifications['date_location'] = scraped
                icon = '✓' if scraped['status'] == 'verified' else '✗'
                _log(f"    date_location: {scraped['status']} {icon} (scraped from website)")
            else:
                _log(f"    date_location: scrape inconclusive → falling back to batch")
                batch_claims['date_location'] = dl_claim
        else:
            batch_claims['date_location'] = dl_claim

    # existence: always Tavily batch
    batch_claims['existence'] = f'{name} is a real conference happening in {year or "2026"}'

    # Prefer grounding URL from generation; fall back to the conference's own website
    entity_grounding_url = conference.get('_grounding_url') or conference.get('website')

    # Clean conference for output AFTER citation extraction
    conference = _clean_entity_fields(conference)

    if batch_claims:
        search_query = f'"{name}" {year} conference'
        batch = _verify_entity_batch(
            entity_name=name,
            search_query=search_query,
            claims=batch_claims,
            log_fn=log_fn,
            use_tavily=use_tavily,
            existing_context=existing_context,
            call_state=call_state,
            search_provider=search_provider,
            grounding_url=entity_grounding_url,
        )
        for field, v in batch.items():
            verifications[field] = v
            icon = '✓' if v['status'] == 'verified' else ('✗' if v['status'] == 'contradicted' else '~')
            _log(f"    {field}: {v['status']} {icon}")

    # date_location contradicted → always low confidence
    if verifications.get('date_location', {}).get('status') == 'contradicted':
        overall = 'low'
    elif verifications.get('existence', {}).get('status') == 'contradicted':
        overall = 'low'
    else:
        overall = _derive_confidence(verifications)
    _log(f"    Overall confidence: {overall}")

    return {
        'conference': conference,
        'verifications': verifications,
        'overall_confidence': overall,
    }


# ---------------------------------------------------------------------------
# Sector brief verification
# ---------------------------------------------------------------------------

def verify_sector_brief(
    sector_brief: str,
    log_fn=None,
    use_tavily: Optional[bool] = None,
    call_state: Optional[dict] = None,
    search_provider: str = "duckduckgo",
) -> dict:
    """
    Citation-first verification for the sector brief.

    Priority:
      1. URL citations → fetch page, secondary LLM call to confirm claim (free of Tavily)
      2. estimated / derived → mark inferred immediately
      3. training_knowledge → mark unverifiable (too many in a sector brief to burn Tavily budget)
      4. No URL citations found → use Gemini web search (if available) or Tavily batch
    """
    from research import _strip_json_fences, _escape_control_chars

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    _log("=== Sector Brief Verification ===")

    # Extract all [SRC: ...] citations from the brief text
    _, citations = _extract_citations(sector_brief)
    url_citations = [c for c in citations if c['citation_type'] == 'url']
    _log(f"> Found {len(citations)} citations, {len(url_citations)} with real URLs")

    verified_claims = []

    if url_citations:
        # --- Citation-first path — fetch all URLs in parallel ---
        def _verify_one_citation(cit):
            claim_text = cit['claim_snippet']
            result = _fetch_and_verify_citation(
                url=cit['citation_url'],
                claim=claim_text,
                entity_name='sector brief',
                log_fn=log_fn,
            )
            return claim_text, result

        with ThreadPoolExecutor(max_workers=min(len(url_citations), 4)) as pool:
            futures = {pool.submit(_verify_one_citation, cit): cit for cit in url_citations}
            for future in as_completed(futures):
                try:
                    claim_text, result = future.result()
                    icon = '✓' if result.get('status') == 'verified' else ('✗' if result.get('status') == 'contradicted' else '?')
                    _log(f">   {claim_text[:70]} → {result.get('status')} {icon}")
                    verified_claims.append({'claim': claim_text, 'verification': result})
                except Exception as e:
                    cit = futures[future]
                    _log(f">   Citation fetch failed: {e}")

        # Mark estimated / derived as inferred
        for cit in citations:
            if cit['citation_type'] in ('estimated', 'derived'):
                verified_claims.append({
                    'claim': cit['claim_snippet'],
                    'verification': {
                        'status': 'inferred',
                        'claim': cit['claim_snippet'],
                        'citation_note': cit['citation_type'],
                    }
                })

    else:
        # --- Fallback: no URL citations ---
        if _verifier_uses_gemini_search():
            # Gemini has native search — use it to verify claims directly (no Tavily)
            _log("> No URL citations — using Gemini web search to verify claims")
            verify_prompt = f"""You are a fact-checker for a private equity research brief.
Use web search to verify the 3 most specific numeric claims (market size, growth rates, percentages).

Sector brief (excerpt):
{sector_brief[:3000]}

For each claim:
1. Search for it
2. Determine: verified (corroborated by a source), contradicted (source says differently), or unverifiable (cannot find)
3. Provide the source URL if verified

Return ONLY a raw JSON array of up to 3 objects:
[{{"claim": "...", "status": "verified|unverifiable|contradicted", "source_url": "https://...|null", "note": "1 sentence"}}]"""
            try:
                raw = _call_verifier_llm(verify_prompt, 800, use_search=True)
                _cleaned = _escape_control_chars(_strip_json_fences(raw))
                try:
                    results = json.loads(_cleaned)
                except json.JSONDecodeError:
                    from json_repair import repair_json
                    results = repair_json(_cleaned, return_objects=True)
                if not isinstance(results, list):
                    results = []
                for r in results:
                    if not isinstance(r, dict):
                        continue
                    status = r.get('status', 'unverifiable')
                    icon = '✓' if status == 'verified' else ('✗' if status == 'contradicted' else '?')
                    _log(f">   {r.get('claim', '')[:60]}... → {status} {icon}")
                    if r.get('source_url'):
                        _log(f">   Source: {r['source_url']}")
                    verified_claims.append({
                        'claim': r.get('claim', ''),
                        'verification': {
                            'status': status,
                            'claim': r.get('claim', ''),
                            'source_url': r.get('source_url'),
                            'note': r.get('note', ''),
                        }
                    })
            except Exception as e:
                _log(f"  Gemini verification failed: {e}")
        else:
            # --- Tavily fallback (non-Google path only) ---
            _log("> No URL citations — falling back to numeric claim extraction + Tavily")

            extract_prompt = f"""Extract the 3 most specific, verifiable numeric claims from this sector brief.
Focus on: market size figures, growth rates, percentages — NOT qualitative statements.
Return ONLY a JSON object with keys "claim_1", "claim_2", "claim_3" (use null if fewer than 3 exist).

Sector brief:
{sector_brief}"""

            try:
                raw = _call_verifier_llm(extract_prompt, max_tokens=200)
                _cleaned = _escape_control_chars(_strip_json_fences(raw))
                try:
                    extracted = json.loads(_cleaned)
                except json.JSONDecodeError:
                    from json_repair import repair_json
                    extracted = repair_json(_cleaned, return_objects=True)
                if not isinstance(extracted, dict):
                    extracted = {}
                claims = {k: v for k, v in extracted.items() if isinstance(v, str) and v.strip()}
            except Exception as e:
                _log(f"  Claim extraction failed: {e}")
                return {'claims': [], 'overall_confidence': None}

            if not claims:
                _log("> No numeric claims extracted — skipping verification")
                return {'claims': [], 'overall_confidence': None}

            _log(f"> Extracted {len(claims)} numeric claims — verifying in 1 Tavily batch call")

            batch = _verify_entity_batch(
                entity_name="this sector",
                search_query=f"sector market size growth rate {list(claims.values())[0][:50]}",
                claims=claims,
                log_fn=log_fn,
                use_tavily=use_tavily,
                call_state=call_state,
                search_provider=search_provider,
            )

            for key, claim_text in claims.items():
                v = batch.get(key, {'status': 'unverifiable'})
                icon = '✓' if v['status'] == 'verified' else ('✗' if v['status'] == 'contradicted' else '?')
                _log(f'> {key}: "{claim_text[:60]}..." → {v["status"]} {icon}')
                verified_claims.append({'claim': claim_text, 'verification': v})

    if not verified_claims:
        return {'claims': [], 'overall_confidence': None}

    overall = _derive_confidence({str(i): c['verification'] for i, c in enumerate(verified_claims)})
    return {'claims': verified_claims, 'overall_confidence': overall}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def verify_field(
    entity_name: str,
    field_name: str,
    claim: str,
    context: str = "",
    use_tavily: Optional[bool] = None,
    log_fn=None,
    search_provider: str = "duckduckgo",
) -> dict:
    """
    On-demand verification of a single field. Used by the /api/verify/field endpoint.
    Returns (verification_dict, tavily_was_used).

    Strategy:
    1. If context provided: try Gemini-only first (no Tavily credit).
    2. If Gemini-only returns verified/contradicted: return immediately.
    3. Otherwise: fall back to _verify_entity_batch with Tavily.
    """
    from research import _strip_json_fences

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    enabled = TAVILY_ENABLED if use_tavily is None else use_tavily

    # Step 1: Try context-only with verifier model (free — no search call)
    if context and context.strip():
        try:
            prompt = f"""You are a fact-checker. Given these search results, assess whether this claim is supported, contradicted, or cannot be determined.

Claim: {claim}

Search results:
{context[:3000]}

Return ONLY a JSON object:
{{
  "verdict": "verified" | "contradicted" | "inferred" | "unverifiable",
  "source_url": "most relevant URL or null",
  "snippet": "brief supporting excerpt or null"
}}

Use "inferred" when the claim is plausible and consistent with the context but not directly cited."""
            raw = _call_verifier_llm(prompt, max_tokens=200)
            _cleaned = _strip_json_fences(raw)
            try:
                parsed = json.loads(_cleaned)
            except json.JSONDecodeError:
                from json_repair import repair_json
                parsed = repair_json(_cleaned, return_objects=True)
                if not isinstance(parsed, dict):
                    raise ValueError(f"json_repair returned non-dict for verify_field: {type(parsed)}")
            verdict = parsed.get('verdict', 'unverifiable')
            if verdict in ('verified', 'contradicted', 'inferred'):
                _log(f"  verify_field: context-only result = {verdict} (no Tavily used)")
                corrected = parsed.get('corrected_value') if verdict == 'contradicted' else None
                return {
                    'status': verdict,
                    'source_url': parsed.get('source_url'),
                    'source_snippet': parsed.get('snippet'),
                    'claim': claim,
                    'corrected_value': corrected,
                }, False
        except Exception as e:
            _log(f"  verify_field: context-only attempt failed — {e}")

    # Step 2: Tavily batch (1 call)
    if not enabled:
        return {'status': 'pending', 'citation_note': 'Tavily verification is disabled in settings', 'claim': claim}, False

    batch = _verify_entity_batch(
        entity_name=entity_name,
        search_query=f'"{entity_name}" {claim[:60]}',
        claims={field_name: claim},
        log_fn=log_fn,
        use_tavily=True,
        existing_context="",   # force fresh search
        call_state=None,
        search_provider=search_provider,
    )
    v = batch.get(field_name, {'status': 'unverifiable', 'claim': claim})
    return v, True


def _derive_confidence(verifications: dict) -> str:
    statuses = [v.get('status') for v in verifications.values()]
    if any(s == 'contradicted' for s in statuses):
        return 'low'
    if sum(1 for s in statuses if s == 'verified') >= 3:
        return 'high'
    return 'medium'


def _wrap_unverified(research_result: dict) -> dict:
    """Wrap raw result in verified shape with all statuses pending."""
    return {
        'sector_brief': research_result['sector_brief'],
        'sector_brief_verification': {'claims': [], 'overall_confidence': None},
        'conferences': [
            {'conference': _clean_entity_fields(c), 'verifications': {}, 'overall_confidence': None}
            for c in research_result.get('conferences', [])
        ],
        'companies': [
            {'company': _clean_entity_fields(c), 'verifications': {}, 'overall_confidence': None}
            for c in research_result.get('companies', [])
        ],
        '_companies_context': '',
        '_conferences_context': '',
    }


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

def verify_research(
    research_result: dict,
    settings: Optional[dict] = None,
    log_fn=None,
    companies_context: str = "",
    conferences_context: str = "",
) -> dict:
    """
    Takes raw run_research() output and returns VerifiedResearchResponse shape.
    Accepts pre-gathered Tavily context to minimize additional credit usage.
    """
    _settings = settings or {}
    use_tavily_setting = _settings.get('verification_tavily_enabled', None)
    use_tavily = TAVILY_ENABLED if use_tavily_setting is None else bool(use_tavily_setting)
    search_provider = _settings.get('search_provider', 'duckduckgo')

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    n_companies = len(research_result.get('companies', []))
    n_confs = len(research_result.get('conferences', []))
    cap_str = f", cap={TAVILY_MAX_CALLS}" if (search_provider == 'tavily' and TAVILY_MAX_CALLS > 0) else ""
    _log(f"=== Verification Pass ===")
    _log(f"  Search: {search_provider} ({'enabled' if use_tavily else 'disabled'}){cap_str} | ~{n_companies + n_confs + 1} calls max")

    # Shared thread-safe call counter for Tavily cap enforcement
    call_state = {'count': 0, '_lock': threading.Lock()}

    companies = research_result.get('companies', [])
    conferences = research_result.get('conferences', [])

    # Run sector brief, all companies, and all conferences in parallel.
    # Each entity gets one search + one LLM call; running them concurrently cuts
    # wall time from O(N) sequential to roughly O(1) — bounded by the slowest entity.
    _log(f"--- Parallel verification: {n_confs} conferences + {n_companies} companies + sector brief ---")

    sector_verification = None
    verified_companies_map = {}   # index → result
    verified_conferences_map = {} # index → result

    def _run_sector_brief():
        return verify_sector_brief(
            research_result['sector_brief'],
            log_fn=log_fn,
            use_tavily=use_tavily,
            call_state=call_state,
            search_provider=search_provider,
        )

    def _run_company(idx, company):
        return idx, verify_company(
            company,
            log_fn=log_fn,
            use_tavily=use_tavily,
            existing_context=companies_context,
            call_state=call_state,
            search_provider=search_provider,
        )

    def _run_conference(idx, conf):
        return idx, verify_conference(
            conf,
            log_fn=log_fn,
            use_tavily=use_tavily,
            existing_context=conferences_context,
            call_state=call_state,
            search_provider=search_provider,
        )

    n_workers = 1 + len(companies) + len(conferences)  # sector brief + each entity
    with ThreadPoolExecutor(max_workers=min(n_workers, 6)) as pool:
        futures = {}
        futures['brief'] = pool.submit(_run_sector_brief)
        for i, c in enumerate(companies):
            futures[('company', i)] = pool.submit(_run_company, i, c)
        for i, cf in enumerate(conferences):
            futures[('conf', i)] = pool.submit(_run_conference, i, cf)

        for future in as_completed(futures.values()):
            key = next(k for k, f in futures.items() if f is future)
            try:
                result = future.result()
                if key == 'brief':
                    sector_verification = result
                    _log("  Sector brief verification complete")
                elif isinstance(key, tuple) and key[0] == 'company':
                    idx, verified = result
                    verified_companies_map[idx] = verified
                    _log(f"  Company verified: {companies[idx].get('name', '?')}")
                elif isinstance(key, tuple) and key[0] == 'conf':
                    idx, verified = result
                    verified_conferences_map[idx] = verified
                    _log(f"  Conference verified: {conferences[idx].get('name', '?')}")
            except Exception as e:
                if key == 'brief':
                    _log(f"  Sector brief verification failed: {e}")
                    sector_verification = {'claims': [], 'overall_confidence': None}
                elif isinstance(key, tuple) and key[0] == 'company':
                    idx = key[1]
                    _log(f"  Company verification failed ({companies[idx].get('name', '?')}): {e}")
                    verified_companies_map[idx] = {
                        'company': companies[idx], 'verifications': {}, 'overall_confidence': None
                    }
                elif isinstance(key, tuple) and key[0] == 'conf':
                    idx = key[1]
                    _log(f"  Conference verification failed ({conferences[idx].get('name', '?')}): {e}")
                    verified_conferences_map[idx] = {
                        'conference': conferences[idx], 'verifications': {}, 'overall_confidence': None
                    }

    # Restore original ordering
    verified_companies = [verified_companies_map[i] for i in range(len(companies))]
    verified_conferences = [verified_conferences_map[i] for i in range(len(conferences))]

    if search_provider == 'tavily':
        _log(f"=== Verification complete — {call_state['count']} Tavily calls used ===")
    else:
        _log(f"=== Verification complete ({search_provider}, no call cap) ===")

    return {
        'sector_brief': research_result['sector_brief'],
        'sector_brief_verification': sector_verification,
        'conferences': verified_conferences,
        'companies': verified_companies,
        '_companies_context': companies_context,
        '_conferences_context': conferences_context,
    }


# ---------------------------------------------------------------------------
# Citation URL repair (post-generation, pre-verification)
# ---------------------------------------------------------------------------

_URL_CITATION_RE = re.compile(r'\[SRC:\s*(https?://[^\]]+)\]')


def repair_sector_brief_citations(
    text: str,
    settings: dict,
    log_fn=None,
    max_repairs: int = 8,
) -> tuple:
    """
    POST-GENERATION CITATION REPAIR

    For every [SRC: https://...] marker in the sector brief:
      1. HEAD-check all unique URLs in parallel.
      2. For 404s / homepage-redirects: search the source domain for the claim
         using the configured search provider (Tavily / DuckDuckGo).
      3. Fetch the best candidate page and ask the verifier LLM whether the
         claim is actually present there.
      4. If verified → replace the broken URL inline in the returned text.

    Returns (repaired_text, repair_log) where repair_log is a list of dicts
    describing each repair attempt.  Runs safely inside a background thread.
    """
    from search import run_search
    from urllib.parse import urlparse
    from bs4 import BeautifulSoup

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    # ------------------------------------------------------------------ #
    # Step 1 – collect all URL citations with their preceding claim text  #
    # ------------------------------------------------------------------ #

    class _Ref:
        __slots__ = ('url', 'claim')
        def __init__(self, u, c):
            self.url = u
            self.claim = c

    refs: list[_Ref] = []
    for m in _URL_CITATION_RE.finditer(text):
        url = m.group(1).strip()
        # Grab the last sentence before the marker as the "claim"
        start = max(0, m.start() - 300)
        preceding = text[start:m.start()]
        for sep in ('. ', '.\n', '!\n', '?\n', '\n\n'):
            pos = preceding.rfind(sep)
            if pos >= 0:
                preceding = preceding[pos + len(sep):]
                break
        refs.append(_Ref(url, preceding.strip()[:150]))

    if not refs:
        return text, []

    # ------------------------------------------------------------------ #
    # Step 2 – HEAD-check all unique URLs in parallel                     #
    # ------------------------------------------------------------------ #

    def _is_broken(url: str) -> tuple:
        """Returns (url, is_broken, reason)."""
        try:
            r = httpx.head(url, timeout=6, follow_redirects=True,
                           headers={"User-Agent": _BROWSER_UA})
            if r.status_code == 404:
                return url, True, 'HTTP 404'
            if r.status_code >= 400:
                return url, True, f'HTTP {r.status_code}'
            # Detect homepage-redirect: specific path collapsed to root
            orig = urlparse(url)
            final = urlparse(str(r.url))
            if (
                orig.path.rstrip('/') not in ('', '/')
                and final.path.rstrip('/') in ('', '/')
                and orig.netloc.lower().lstrip('www.') == final.netloc.lower().lstrip('www.')
            ):
                return url, True, 'Redirected to homepage (page missing)'
            return url, False, ''
        except httpx.TimeoutException:
            return url, False, ''   # timeout → leave alone
        except Exception:
            return url, False, ''

    unique_urls = list({r.url for r in refs})
    broken_map: dict = {}  # url → reason
    with ThreadPoolExecutor(max_workers=min(len(unique_urls), 5)) as pool:
        for url, is_broken, reason in pool.map(_is_broken, unique_urls):
            if is_broken:
                broken_map[url] = reason

    if not broken_map:
        _log(f"Citation repair: all {len(unique_urls)} citation URL(s) are live — nothing to fix")
        return text, []

    _log(f"Citation repair: {len(broken_map)}/{len(unique_urls)} broken citation(s) — searching for replacements")

    # ------------------------------------------------------------------ #
    # Step 3 – for each broken URL, find and verify a replacement         #
    # ------------------------------------------------------------------ #

    search_provider = (settings or {}).get('search_provider', 'duckduckgo')
    url_replacement: dict = {}   # broken_url → working_url | None
    repair_log: list = []
    repairs_attempted = 0

    for broken_url, broken_reason in broken_map.items():
        if repairs_attempted >= max_repairs:
            break
        repairs_attempted += 1

        # Find claim for this URL (first occurrence)
        ref = next((r for r in refs if r.url == broken_url), None)
        if not ref:
            url_replacement[broken_url] = None
            continue

        claim = ref.claim

        # Gemini grounding redirect URLs (vertexaisearch.cloud.google.com) are
        # short-lived tokens. Follow the redirect to get the real source page;
        # if it's still live use it directly, otherwise skip — searching
        # site:vertexaisearch.cloud.google.com never returns results.
        if 'vertexaisearch.cloud.google.com' in broken_url:
            try:
                rr = httpx.get(broken_url, timeout=8, follow_redirects=True,
                               headers={"User-Agent": _BROWSER_UA})
                dest = str(rr.url)
                if 'vertexaisearch.cloud.google.com' not in dest and rr.status_code < 400:
                    _log(f"  vertexai redirect resolved → {dest}")
                    url_replacement[broken_url] = dest
                    repair_log.append({'broken_url': broken_url, 'replacement_url': dest,
                                       'verdict': 'redirect_resolved'})
                    continue
            except Exception:
                pass
            _log(f"  vertexai redirect expired/unresolvable — skipping")
            url_replacement[broken_url] = None
            repair_log.append({'broken_url': broken_url, 'verdict': 'vertexai_unresolvable'})
            continue

        domain = urlparse(broken_url).netloc or broken_url
        record = {
            'broken_url': broken_url,
            'broken_reason': broken_reason,
            'claim': claim,
            'domain': domain,
            'replacement_url': None,
            'verdict': 'unverifiable',
            'supporting_excerpt': None,
        }

        try:
            query = f'site:{domain} {claim[:80]}'
            _log(f"  Searching: {query[:90]}…")
            results = run_search(query, provider=search_provider)

            # Filter to same domain, exclude the known-broken URL
            candidates = [
                r for r in results
                if r.get('url')
                and domain in r.get('url', '')
                and r.get('url') != broken_url
            ][:3]

            if not candidates:
                _log(f"  No candidates found for {domain}")
                url_replacement[broken_url] = None
                repair_log.append(record)
                continue

            # Try candidates until one is verified
            found = False
            for candidate in candidates:
                candidate_url = candidate.get('url', '')
                if not candidate_url:
                    continue

                # Quick pre-filter: significant claim words in search snippet
                snippet_text = (candidate.get('content', '') + ' ' + candidate.get('title', '')).lower()
                claim_words = [w.lower() for w in claim.split() if len(w) > 4]
                hits = sum(1 for w in claim_words if w in snippet_text)
                if claim_words and hits < max(1, len(claim_words) // 4):
                    continue   # snippet doesn't mention the claim at all

                # Fetch the candidate page
                try:
                    page_resp = httpx.get(
                        candidate_url, timeout=10, follow_redirects=True,
                        headers={"User-Agent": _BROWSER_UA},
                    )
                    if page_resp.status_code >= 400:
                        continue
                    soup = BeautifulSoup(page_resp.text, "lxml")
                    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
                        tag.decompose()
                    body = (
                        soup.find("article") or soup.find("main")
                        or soup.find(attrs={"role": "main"})
                        or soup.find(class_="content") or soup.find(id="content")
                        or soup.body
                    )
                    if not body:
                        continue
                    page_text = re.sub(r"\s{2,}", " ", body.get_text(separator=" ", strip=True))[:3000]
                except Exception:
                    continue

                if not page_text.strip():
                    continue

                # Ask the verifier LLM: is the claim on this page?
                try:
                    from research import _strip_json_fences as _sfences
                    verify_prompt = (
                        f'A sector-brief citation URL returned an error ({broken_reason}). '
                        f'We found a candidate replacement page on the same domain.\n\n'
                        f'Original claim: "{claim}"\n'
                        f'Original (broken) URL: {broken_url}\n'
                        f'Candidate URL: {candidate_url}\n\n'
                        f'Page content (excerpt):\n{page_text}\n\n'
                        f'Does the candidate page support the claim above?\n\n'
                        f'Return ONLY a JSON object:\n'
                        f'{{"verdict":"verified"|"contradicted"|"unverifiable",'
                        f'"supporting_excerpt":"direct quote from page (max 100 chars) or null"}}'
                    )
                    raw = _call_verifier_llm(verify_prompt, max_tokens=200)
                    parsed = json.loads(_sfences(raw))
                    verdict = parsed.get('verdict', 'unverifiable')
                    if verdict not in ('verified', 'contradicted', 'unverifiable'):
                        verdict = 'unverifiable'
                    excerpt = parsed.get('supporting_excerpt')
                    _log(f"  {verdict}: {candidate_url}")

                    if verdict == 'verified':
                        url_replacement[broken_url] = candidate_url
                        record['replacement_url'] = candidate_url
                        record['verdict'] = verdict
                        record['supporting_excerpt'] = excerpt
                        found = True
                        break
                except Exception as e:
                    _log(f"  LLM check failed for {candidate_url}: {e}")
                    continue

            if not found:
                _log(f"  No verified replacement found for {broken_url}")
                url_replacement[broken_url] = None

        except Exception as e:
            _log(f"  Repair search failed for {broken_url}: {e}")
            url_replacement[broken_url] = None

        repair_log.append(record)

    # ------------------------------------------------------------------ #
    # Step 4 – replace broken URLs in text                                #
    # ------------------------------------------------------------------ #

    repairs_made = sum(1 for v in url_replacement.values() if v)
    if not repairs_made:
        _log("Citation repair: no verified replacements found — text unchanged")
        return text, repair_log

    def _sub(m):
        url = m.group(1).strip()
        replacement = url_replacement.get(url)
        return f'[SRC: {replacement}]' if replacement else m.group(0)

    repaired = _URL_CITATION_RE.sub(_sub, text)
    _log(f"Citation repair: replaced {repairs_made} broken URL(s) with verified alternatives")
    return repaired, repair_log
