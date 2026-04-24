"""
enrichment.py — Contact enrichment for DealScout decision makers.

Three methods per person (Methods 1 & 2 are fast; all DMs run in parallel via profile.py):
  1. Website scraping — fetch /team, /contact, /about, homepage concurrently for email + phone
  2. Pattern generation — generate most-likely email pattern at low confidence (instant)
  3. Gemini web search  — LLM-powered search for contact info in public records

Always returns a ContactInfo object. Never raises.
"""

import json
import logging
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from typing import Optional

import httpx
import phonenumbers
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Country name → ISO 3166-1 alpha-2 (for phonenumbers region hint)
_COUNTRY_ISO = {
    "Germany": "DE", "Austria": "AT", "Switzerland": "CH",
    "France": "FR", "Netherlands": "NL", "Belgium": "BE",
    "Sweden": "SE", "Norway": "NO", "Denmark": "DK", "Finland": "FI",
    "Spain": "ES", "Italy": "IT", "Poland": "PL",
    "United Kingdom": "GB", "UK": "GB",
    "Portugal": "PT", "Ireland": "IE",
    "Czech Republic": "CZ", "Romania": "RO", "Hungary": "HU",
    "Estonia": "EE", "Latvia": "LV", "Lithuania": "LT",
    "Slovakia": "SK", "Slovenia": "SI", "Croatia": "HR",
    "Bulgaria": "BG", "Greece": "GR", "Luxembourg": "LU",
}

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_PHONE_RE = re.compile(r"[\+\(]?[0-9][0-9 \-\(\)]{7,}[0-9]")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


# ---------------------------------------------------------------------------
# ContactInfo dataclass (mirrors models.py but plain dict for internal use)
# ---------------------------------------------------------------------------

def _empty_contact():
    return {
        "email": None, "email_confidence": None, "email_source": None,
        "email_alternatives": None,
        "phone": None, "phone_confidence": None, "phone_source": None,
        "enrichment_notes": None,
    }


def _resolve_email_candidates(contact: dict, candidates: list, log_fn) -> None:
    """
    Pick a winner from collected email candidates.
    High/medium → single primary. Multiple low → surface all as alternatives.
    """
    if not candidates:
        return
    high_med = [c for c in candidates if c.get("confidence") in ("high", "medium")]
    low = [c for c in candidates if c.get("confidence") == "low"]
    if high_med:
        best = high_med[0]
        contact["email"] = best["email"]
        contact["email_confidence"] = best["confidence"]
        contact["email_source"] = best["source"]
    elif len(low) > 1:
        contact["email"] = None
        contact["email_confidence"] = None
        contact["email_source"] = None
        contact["email_alternatives"] = low
        log_fn(f"  Enrichment: {len(low)} low-confidence candidates — surfacing all")
    elif len(low) == 1:
        contact["email"] = low[0]["email"]
        contact["email_confidence"] = low[0]["confidence"]
        contact["email_source"] = low[0]["source"]


def _is_complete(c: dict) -> bool:
    """Both email and phone found at high confidence."""
    return (
        c.get("email") and c.get("email_confidence") == "high"
        and c.get("phone") and c.get("phone_confidence") == "high"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_page(url: str) -> Optional[str]:
    """Fetch a URL, return HTML string or None on failure. Caps at 200 KB."""
    try:
        with httpx.Client(timeout=5, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _BROWSER_UA})
            if resp.status_code == 200:
                return resp.text[:200_000]
    except Exception:
        pass
    return None


def _extract_emails_from_html(html: str) -> list:
    """Extract mailto: hrefs + inline email patterns from HTML."""
    soup = BeautifulSoup(html, "lxml")
    found = []
    # mailto: hrefs
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if addr and _EMAIL_RE.match(addr):
                found.append(addr)
    # inline patterns
    text = soup.get_text(separator=" ")
    found += _EMAIL_RE.findall(text)
    # deduplicate preserving order
    seen, out = set(), []
    for e in found:
        el = e.lower()
        if el not in seen:
            seen.add(el)
            out.append(e)
    return out


def _extract_phones_from_text(text: str, country_iso: Optional[str]) -> list:
    """Find phone numbers in text, return E.164 formatted strings."""
    raw_matches = _PHONE_RE.findall(text)
    results = []
    for raw in raw_matches:
        cleaned = raw.strip()
        try:
            parsed = phonenumbers.parse(cleaned, country_iso)
            if phonenumbers.is_valid_number(parsed):
                results.append(phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                ))
        except Exception:
            pass
    return results


def _ascii_name(s: str) -> str:
    """Normalize accented chars to ASCII."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if unicodedata.category(c) != "Mn"
    ).lower()


def _email_candidates(first: str, last: str, domain: str) -> list:
    f = _ascii_name(first)
    l = _ascii_name(last)
    fi = f[0] if f else ""
    return [
        f"{f}@{domain}",
        f"{f}.{l}@{domain}",
        f"{fi}.{l}@{domain}",
        f"{fi}{l}@{domain}",
        f"{l}@{domain}",
    ]


# ---------------------------------------------------------------------------
# Method 0 — PDL (People Data Labs) — LinkedIn URL only on free tier
# ---------------------------------------------------------------------------

def _query_pdl(name: str, company_name: str, log_fn=None) -> Optional[str]:
    """
    Look up a person's LinkedIn URL via PDL Person Enrichment API.
    Free tier: 100 lookups/month. Returns linkedin_url string or None.
    """
    api_key = os.getenv("PDL_API_KEY", "")
    if not api_key:
        return None
    try:
        params = {
            "name": name,
            "company": company_name,
            "pretty": "false",
        }
        resp = httpx.get(
            "https://api.peopledatalabs.com/v5/person/enrich",
            params=params,
            headers={"X-Api-Key": api_key, "User-Agent": "DealScout/1.0"},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            linkedin = data.get("data", {}).get("linkedin_url") or data.get("linkedin_url")
            if linkedin:
                if log_fn:
                    log_fn(f"  PDL: LinkedIn URL found for {name}")
                return linkedin if linkedin.startswith("http") else f"https://{linkedin}"
        elif resp.status_code == 404:
            pass  # no match — not an error
        else:
            logger.debug("PDL HTTP %s for %s", resp.status_code, name)
    except Exception as exc:
        logger.debug("PDL lookup failed for %s: %s", name, exc)
    return None


# ---------------------------------------------------------------------------
# Method 1 — Website scraping
# ---------------------------------------------------------------------------

def _method1_website(
    last_name: str,
    company_website: Optional[str],
    country_iso: Optional[str],
    log_fn,
) -> dict:
    contact = _empty_contact()
    if not company_website:
        log_fn("  Method 1: No website — skipping")
        return contact

    base = company_website.rstrip("/")
    pages = [
        f"{base}/team", f"{base}/contact", f"{base}/about",
        base,
    ]

    log_fn("  Method 1: Scraping company website (parallel)...")

    # Fetch all candidate pages concurrently
    page_results: dict[str, Optional[str]] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_to_url = {pool.submit(_fetch_page, url): url for url in pages}
        try:
            for future in as_completed(future_to_url, timeout=8):
                url = future_to_url[future]
                try:
                    page_results[url] = future.result()
                except Exception:
                    page_results[url] = None
        except FuturesTimeoutError:
            log_fn("  Method 1: Page fetch timed out — using partial results")

    # Process pages in priority order (team → contact → about → homepage)
    for page_url in pages:
        html = page_results.get(page_url)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(separator=" ")
        idx = text.lower().find(last_name.lower())
        if idx == -1:
            continue  # person not mentioned on this page

        window = text[max(0, idx - 200): idx + 2000]

        if not contact.get("email"):
            emails = _extract_emails_from_html(html)
            window_emails = [e for e in _EMAIL_RE.findall(window) if _EMAIL_RE.fullmatch(e)]
            all_emails = [e for e in emails if _EMAIL_RE.fullmatch(e)]
            chosen = window_emails[0] if window_emails else (all_emails[0] if all_emails else None)
            if chosen:
                contact["email"] = chosen
                contact["email_confidence"] = "high"
                contact["email_source"] = "website"
                log_fn(f"  Method 1: Found email on {page_url} (high confidence)")

        if not contact.get("phone"):
            phones = _extract_phones_from_text(window, country_iso)
            if phones:
                contact["phone"] = phones[0]
                contact["phone_confidence"] = "high"
                contact["phone_source"] = "website"
                log_fn(f"  Method 1: Found phone number (high confidence)")

        if contact.get("email") or contact.get("phone"):
            return contact

    log_fn("  Method 1: No contact info found on website pages")
    return contact


# ---------------------------------------------------------------------------
# Method 2 — Email pattern generation (low confidence, instant)
# SMTP probing removed: blocked by virtually all modern providers (Google
# Workspace, M365), wastes ~25 s per person, and yields the same low-
# confidence pattern we generate here directly.
# ---------------------------------------------------------------------------

def _method2_pattern(first: str, last: str, domain: str, log_fn) -> dict:
    contact = _empty_contact()
    if not domain or not first or not last:
        return contact
    candidates = _email_candidates(first, last, domain)
    contact["email"] = candidates[0]
    contact["email_confidence"] = "low"
    contact["email_source"] = "pattern_unverified"
    contact["enrichment_notes"] = "Email pattern generated; not SMTP-verified"
    log_fn(f"  Method 2: Generated pattern {candidates[0]} (low confidence)")
    return contact


# ---------------------------------------------------------------------------
# Method 3 — Gemini web search
# ---------------------------------------------------------------------------

def _method3_web_search(
    name: str,
    title: str,
    company_name: str,
    company_website: Optional[str],
    log_fn,
) -> dict:
    contact = _empty_contact()
    try:
        from research import _call_llm
        log_fn("  Method 3: AI web search...")

        prompt = f"""Find the professional email address and/or direct phone number for {name}, who is {title} at {company_name} ({company_website or 'website unknown'}).

Search for:
- Their name + company in press releases, news articles, conference speaker bios
- Their name on GitHub, personal website, or company blog author pages
- Company filings or registry entries that list director contact details
- Any public appearances where contact info was listed

IMPORTANT: Only return an email if you found a complete, valid email address (e.g. john.smith@company.com).
Do NOT guess or construct an email pattern. Do NOT return a partial address (e.g. "john" or "john.smith").
If you cannot find a confirmed, complete email address, set email to null.

Return ONLY a raw JSON object:
{{
  "email": "complete email address or null",
  "email_source_url": "URL where email was found or null",
  "phone": "phone number or null",
  "phone_source_url": "URL where phone was found or null",
  "notes": "string or null"
}}"""

        from research import _strip_json_fences, _escape_control_chars
        raw = _call_llm(prompt, 500, use_search=True)
        cleaned = _escape_control_chars(_strip_json_fences(raw))
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            from json_repair import repair_json
            data = repair_json(cleaned, return_objects=True)
            if not isinstance(data, dict):
                data = {}

        raw_email = (data.get("email") or "").strip()
        if raw_email and _EMAIL_RE.fullmatch(raw_email):
            contact["email"] = raw_email
            contact["email_confidence"] = "medium"
            contact["email_source"] = "web_search"
            src = data.get("email_source_url", "")
            log_fn(f"  Method 3: Found email{' at ' + src if src else ''} (medium confidence)")
        elif raw_email and company_website:
            # Attempt to complete a partial/truncated address using the company domain.
            # Covers two cases:
            #   "fs@"           → LLM had the domain but JSON got truncated (e.g. max_tokens)
            #   "christian.heidl" → LLM returned local-part only (no @)
            dm_match = re.search(r"https?://(?:www\.)?([^/]+)", company_website)
            if dm_match:
                company_domain = dm_match.group(1)
                local = raw_email.rstrip('@')  # strip trailing @ if present
                completed = f"{local}@{company_domain}" if '@' not in local else raw_email
                if _EMAIL_RE.fullmatch(completed):
                    contact["email"] = completed
                    contact["email_confidence"] = "low"
                    contact["email_source"] = "web_search_completed"
                    log_fn(f"  Method 3: Completed partial email '{raw_email}' → '{completed}' (low confidence)")
                else:
                    log_fn(f"  Method 3: Rejected malformed email '{raw_email}' (not a valid address)")
            else:
                log_fn(f"  Method 3: Rejected malformed email '{raw_email}' (not a valid address)")
        elif raw_email:
            log_fn(f"  Method 3: Rejected malformed email '{raw_email}' (not a valid address)")

        if data.get("phone"):
            contact["phone"] = data["phone"]
            contact["phone_confidence"] = "medium"
            contact["phone_source"] = "web_search"
            log_fn(f"  Method 3: Found phone (medium confidence)")

        notes_parts = []
        if data.get("email_source_url"):
            notes_parts.append(f"Email source: {data['email_source_url']}")
        if data.get("phone_source_url"):
            notes_parts.append(f"Phone source: {data['phone_source_url']}")
        if data.get("notes"):
            notes_parts.append(data["notes"])
        if notes_parts:
            contact["enrichment_notes"] = " | ".join(notes_parts)

    except Exception as e:
        log_fn(f"  Method 3: Failed ({e})")

    return contact


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def enrich_contact(
    name: str,
    title: str,
    company_name: str,
    company_website: Optional[str],
    company_country: Optional[str] = None,
    log_fn=None,
    pdl_enabled: bool = True,
) -> dict:
    """
    Attempt to find email + phone for a decision maker using 3 methods.
    Returns a ContactInfo-shaped dict. Never raises.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    try:
        contact = _empty_contact()
        country_iso = _COUNTRY_ISO.get(company_country or "", None)

        # Parse name parts
        parts = name.strip().split()
        last_name = parts[-1] if parts else name
        first_name = parts[0] if len(parts) > 1 else ""

        # Derive domain
        domain = None
        if company_website:
            m = re.search(r"https?://(?:www\.)?([^/]+)", company_website)
            if m:
                domain = m.group(1)

        email_candidates = []  # {email, confidence, source} — resolved at end

        # --- Method 0: PDL — LinkedIn URL (authoritative over LLM-inferred) ---
        if pdl_enabled:
            pdl_linkedin = _query_pdl(name, company_name, _log)
            if pdl_linkedin:
                contact["linkedin_url"] = pdl_linkedin  # promoted to dm level by profile.py

        # --- Method 1: Website scraping ---
        m1 = _method1_website(last_name, company_website, country_iso, _log)
        if m1.get("email"):
            email_candidates.append({"email": m1["email"], "confidence": m1.get("email_confidence"), "source": m1.get("email_source")})
        for k in ("phone", "phone_confidence", "phone_source"):
            if m1.get(k) is not None:
                contact[k] = m1[k]

        # Early exit: website found both email (high) and phone (high) — no alternatives needed
        if email_candidates and email_candidates[0]["confidence"] == "high" and contact.get("phone_confidence") == "high":
            contact["email"] = email_candidates[0]["email"]
            contact["email_confidence"] = email_candidates[0]["confidence"]
            contact["email_source"] = email_candidates[0]["source"]
            _log(f"  Enrichment complete — email: high, phone: high")
            return contact

        # --- Method 2: Email pattern (instant) — skip if already have high/medium candidate ---
        if not any(c["confidence"] in ("high", "medium") for c in email_candidates):
            if domain and first_name and last_name:
                m2 = _method2_pattern(first_name, last_name, domain, _log)
                if m2.get("email"):
                    email_candidates.append({"email": m2["email"], "confidence": m2.get("email_confidence"), "source": m2.get("email_source")})

        # --- Method 3: Gemini web search (if anything still missing at high/medium confidence) ---
        email_ok = any(c["confidence"] in ("high", "medium") for c in email_candidates)
        phone_ok = contact.get("phone") and contact.get("phone_confidence") in ("high", "medium")

        if not email_ok or not phone_ok:
            m3 = _method3_web_search(name, title, company_name, company_website, _log)
            if m3.get("email"):
                existing_emails = {c["email"].lower() for c in email_candidates}
                if m3["email"].lower() not in existing_emails:
                    email_candidates.append({"email": m3["email"], "confidence": m3.get("email_confidence"), "source": m3.get("email_source")})
            if not contact.get("phone") and m3.get("phone"):
                contact["phone"] = m3["phone"]
                contact["phone_confidence"] = m3.get("phone_confidence")
                contact["phone_source"] = m3.get("phone_source")
            if m3.get("enrichment_notes"):
                existing = contact.get("enrichment_notes") or ""
                contact["enrichment_notes"] = (existing + " | " + m3["enrichment_notes"]).strip(" | ")

        # --- Resolve email candidates ---
        _resolve_email_candidates(contact, email_candidates, _log)

        # Summarise
        if contact.get("email_alternatives"):
            _log(f"  Enrichment complete — email: {len(contact['email_alternatives'])} low-confidence candidates, phone: {contact.get('phone_confidence') or 'none'}")
        else:
            e_conf = contact.get("email_confidence") or "none"
            p_conf = contact.get("phone_confidence") or "none"
            _log(f"  Enrichment complete — email: {e_conf}, phone: {p_conf}")

        if not contact.get("email") and not contact.get("email_alternatives") and not contact.get("phone"):
            contact["enrichment_notes"] = "No contact info found via automated methods"

        return contact

    except Exception as e:
        logger.exception("enrich_contact failed for %s", name)
        return {**_empty_contact(), "enrichment_notes": f"Enrichment error: {e}"}
