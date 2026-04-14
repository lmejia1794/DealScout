"""
enrichment.py — Contact enrichment for DealScout decision makers.

Three sequential methods per person:
  1. Website scraping    — scrape /team, /about, /contact pages for email + phone
  2. SMTP verification   — generate email patterns, verify via SMTP handshake
  3. Gemini web search   — LLM-powered search for contact info in public records

Always returns a ContactInfo object. Never raises.
"""

import json
import logging
import os
import re
import smtplib
import unicodedata
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
        "phone": None, "phone_confidence": None, "phone_source": None,
        "enrichment_notes": None,
    }


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
    """Fetch a URL, return HTML string or None on failure."""
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _BROWSER_UA})
            if resp.status_code == 200:
                return resp.text
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
        f"{base}/team", f"{base}/about", f"{base}/about-us",
        f"{base}/contact", f"{base}/management", f"{base}/leadership",
        base,
    ]

    log_fn("  Method 1: Scraping company website...")
    for page_url in pages:
        html = _fetch_page(page_url)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(separator=" ")
        idx = text.lower().find(last_name.lower())
        if idx == -1:
            continue  # person not mentioned on this page

        # Extract from a window around the name mention
        window = text[max(0, idx - 200): idx + 2000]

        if not contact.get("email"):
            emails = _extract_emails_from_html(html)
            # prefer emails near the name
            window_emails = _EMAIL_RE.findall(window)
            chosen = window_emails[0] if window_emails else (emails[0] if emails else None)
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
            return contact  # found something — stop paging

    log_fn("  Method 1: No contact info found on website pages")
    return contact


# ---------------------------------------------------------------------------
# Method 2 — SMTP verification
# ---------------------------------------------------------------------------

def _smtp_verify(email: str, mx_host: str) -> bool:
    try:
        with smtplib.SMTP(mx_host, 25, timeout=5) as smtp:
            smtp.ehlo("dealscout.app")
            code, _ = smtp.rcpt(email)
            return code == 250
    except Exception:
        return False


def _method2_smtp(
    first: str,
    last: str,
    domain: str,
    log_fn,
) -> dict:
    contact = _empty_contact()
    if not domain or not first or not last:
        return contact

    candidates = _email_candidates(first, last, domain)
    log_fn(f"  Method 2: Trying SMTP verification ({len(candidates)} patterns)...")

    try:
        import dns.resolver
        records = dns.resolver.resolve(domain, "MX")
        mx_host = str(sorted(records, key=lambda r: r.preference)[0].exchange).rstrip(".")
    except Exception as e:
        log_fn(f"  Method 2: DNS lookup failed ({e}) — using pattern as low confidence")
        contact["email"] = candidates[0]
        contact["email_confidence"] = "low"
        contact["email_source"] = "pattern_unverified"
        contact["enrichment_notes"] = f"DNS lookup failed: {e}"
        return contact

    smtp_blocked = False
    all_550 = True

    for candidate in candidates:
        try:
            verified = _smtp_verify(candidate, mx_host)
            if verified:
                contact["email"] = candidate
                contact["email_confidence"] = "high"
                contact["email_source"] = "smtp_verified"
                log_fn(f"  Method 2: SMTP verified {candidate}")
                return contact
            else:
                # 550 = exists but rejected — domain is valid
                pass
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ["refused", "timed out", "timeout", "blocked"]):
                smtp_blocked = True
                all_550 = False
            log_fn(f"  Method 2: SMTP error for {candidate}: {e}")

    # Fall back to first pattern at low confidence
    contact["email"] = candidates[0]
    contact["email_confidence"] = "low"
    contact["email_source"] = "pattern_unverified"
    if smtp_blocked:
        note = "SMTP verification blocked by mail provider"
        log_fn(f"  Method 2: {note} — pattern saved as low confidence")
    else:
        note = "SMTP returned 550 for all patterns"
        log_fn(f"  Method 2: {note} — pattern saved as low confidence")
    contact["enrichment_notes"] = note
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
        from research import _call_openrouter
        model = os.getenv("WEB_LLM_MODEL", "google/gemini-2.0-flash-001")
        log_fn("  Method 3: Gemini web search...")

        prompt = f"""Find the professional email address and/or direct phone number for {name}, who is {title} at {company_name} ({company_website or 'website unknown'}).

Search for:
- Their name + company in press releases, news articles, conference speaker bios
- Their name on GitHub, personal website, or company blog author pages
- Company filings or registry entries that list director contact details
- Any public appearances where contact info was listed

Return ONLY a raw JSON object:
{{
  "email": "string or null",
  "email_source_url": "string or null",
  "phone": "string or null",
  "phone_source_url": "string or null",
  "notes": "string or null"
}}"""

        from research import _strip_json_fences
        raw = _call_openrouter(model, prompt, 300)
        data = json.loads(_strip_json_fences(raw))

        if data.get("email"):
            contact["email"] = data["email"]
            contact["email_confidence"] = "medium"
            contact["email_source"] = "web_search"
            src = data.get("email_source_url", "")
            log_fn(f"  Method 3: Found email{' at ' + src if src else ''} (medium confidence)")

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

        # --- Method 1: Website scraping ---
        m1 = _method1_website(last_name, company_website, country_iso, _log)
        contact.update({k: v for k, v in m1.items() if v is not None})

        if _is_complete(contact):
            _log(f"  Enrichment complete — email: {contact.get('email_confidence')}, phone: {contact.get('phone_confidence')}")
            return contact

        # --- Method 2: SMTP verification (email only, only if not already found) ---
        if not contact.get("email") and domain and first_name and last_name:
            m2 = _method2_smtp(first_name, last_name, domain, _log)
            contact.update({k: v for k, v in m2.items() if v is not None and not contact.get(k)})

        if _is_complete(contact):
            _log(f"  Enrichment complete — email: {contact.get('email_confidence')}, phone: {contact.get('phone_confidence')}")
            return contact

        # --- Method 3: Gemini web search (if anything still missing at low confidence or absent) ---
        email_ok = contact.get("email") and contact.get("email_confidence") in ("high", "medium")
        phone_ok = contact.get("phone") and contact.get("phone_confidence") in ("high", "medium")

        if not email_ok or not phone_ok:
            m3 = _method3_web_search(name, title, company_name, company_website, _log)
            if not contact.get("email") and m3.get("email"):
                contact["email"] = m3["email"]
                contact["email_confidence"] = m3.get("email_confidence")
                contact["email_source"] = m3.get("email_source")
            if not contact.get("phone") and m3.get("phone"):
                contact["phone"] = m3["phone"]
                contact["phone_confidence"] = m3.get("phone_confidence")
                contact["phone_source"] = m3.get("phone_source")
            if m3.get("enrichment_notes"):
                existing = contact.get("enrichment_notes") or ""
                contact["enrichment_notes"] = (existing + " | " + m3["enrichment_notes"]).strip(" | ")

        # Summarise
        e_conf = contact.get("email_confidence") or "none"
        p_conf = contact.get("phone_confidence") or "none"
        _log(f"  Enrichment complete — email: {e_conf}, phone: {p_conf}")

        if not contact.get("email") and not contact.get("phone"):
            contact["enrichment_notes"] = "No contact info found via automated methods"

        return contact

    except Exception as e:
        logger.exception("enrich_contact failed for %s", name)
        return {**_empty_contact(), "enrichment_notes": f"Enrichment error: {e}"}
