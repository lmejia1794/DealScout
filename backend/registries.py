"""
registries.py — Company data enrichment from authoritative external sources.

Source hierarchy (applied in enrich_company):
  1. Companies House / Wikidata  → authoritative; overwrites LLM-inferred fields
  2. NewsAPI                     → real-time signals; appended to company data
  3. Clearbit Logo               → free CDN, no key

PDL is handled separately in enrichment.py (contact/LinkedIn use case).
"""

import logging
import os
import re
from typing import Optional
from urllib.parse import urlparse, urlencode, quote

import httpx

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Legal-form suffixes to strip before name-similarity comparison
_SUFFIX_RE = re.compile(
    r'\b(ltd|limited|gmbh|bv|b\.v\.|sas|s\.a\.s\.|ab|as|a\.s\.|aps|apS|oy|spa|s\.p\.a\.|'
    r'nv|n\.v\.|plc|inc|llc|ag|a\.g\.|se|s\.e\.|sarl|s\.a\.r\.l\.|kft|srl|s\.r\.l\.)\b',
    re.IGNORECASE,
)

# Session-level news cache — avoids duplicate NewsAPI calls within a run
_news_cache: dict = {}


# ---------------------------------------------------------------------------
# Name similarity helper
# ---------------------------------------------------------------------------

def _name_similarity(a: str, b: str) -> float:
    """Simple character-overlap ratio after stripping legal suffixes."""
    def _clean(s):
        s = _SUFFIX_RE.sub('', s.lower())
        return re.sub(r'[^a-z0-9 ]', '', s).strip()

    a, b = _clean(a), _clean(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    # Character bigram overlap
    def bigrams(s):
        return {s[i:i+2] for i in range(len(s) - 1)}
    bg_s, bg_l = bigrams(shorter), bigrams(longer)
    if not bg_s:
        return 1.0 if shorter in longer else 0.0
    overlap = len(bg_s & bg_l)
    return overlap / max(len(bg_s), len(bg_l))


# ---------------------------------------------------------------------------
# Function 1 — Companies House (UK only)
# ---------------------------------------------------------------------------

def query_companies_house(company_name: str, log_fn=None) -> Optional[dict]:
    """
    Search Companies House for a UK-registered company.
    Returns None if key not set, no match, or error.
    """
    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    api_key = os.getenv("COMPANIES_HOUSE_API_KEY", "")
    if not api_key:
        return None

    try:
        search_resp = httpx.get(
            "https://api.company-information.service.gov.uk/search/companies",
            params={"q": company_name, "items_per_page": 5},
            auth=(api_key, ""),
            timeout=8,
            headers={"User-Agent": "DealScout/1.0"},
        )
        if search_resp.status_code != 200:
            _log(f"Companies House search HTTP {search_resp.status_code}")
            return None

        items = search_resp.json().get("items", [])
        if not items:
            return None

        # Find best name match
        best_item, best_score = None, 0.0
        for item in items:
            title = item.get("title", "")
            score = _name_similarity(company_name, title)
            if score > best_score:
                best_score = score
                best_item = item

        if best_score <= 0.8 or not best_item:
            _log(f"Companies House: no confident match for '{company_name}' (best score {best_score:.2f})")
            return None

        company_number = best_item.get("company_number", "")
        detail_resp = httpx.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}",
            auth=(api_key, ""),
            timeout=8,
            headers={"User-Agent": "DealScout/1.0"},
        )
        if detail_resp.status_code != 200:
            return None
        d = detail_resp.json()

        addr_parts = d.get("registered_office_address", {})
        addr = ", ".join(
            filter(None, [
                addr_parts.get("address_line_1"), addr_parts.get("locality"),
                addr_parts.get("postal_code"), addr_parts.get("country"),
            ])
        )
        _log(f"Companies House: matched '{d.get('company_name')}' (confidence {best_score:.2f})")
        return {
            "source": "companies_house",
            "match_confidence": round(best_score, 3),
            "registered_name": d.get("company_name", ""),
            "company_number": company_number,
            "status": d.get("company_status", ""),
            "incorporated_on": d.get("date_of_creation", ""),
            "registered_address": addr,
            "company_type": d.get("type", ""),
            "sic_codes": d.get("sic_codes", []),
            "officers_url": f"https://api.company-information.service.gov.uk/company/{company_number}/officers",
        }
    except Exception as exc:
        _log(f"Companies House error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Function 2 — Wikidata (free, no key)
# ---------------------------------------------------------------------------

def query_wikidata(company_name: str, log_fn=None) -> Optional[dict]:
    """
    Query Wikidata SPARQL for company data. Free, no key required.
    """
    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    sparql = f"""
SELECT ?entity ?entityLabel ?inception ?countryLabel ?website ?employees WHERE {{
  ?entity rdfs:label "{company_name}"@en .
  ?entity wdt:P31/wdt:P279* wd:Q4830453 .
  OPTIONAL {{ ?entity wdt:P571 ?inception . }}
  OPTIONAL {{ ?entity wdt:P17 ?country . }}
  OPTIONAL {{ ?entity wdt:P856 ?website . }}
  OPTIONAL {{ ?entity wdt:P1128 ?employees . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
}}
LIMIT 1
"""
    try:
        resp = httpx.get(
            "https://query.wikidata.org/sparql",
            params={"query": sparql, "format": "json"},
            headers={"User-Agent": "DealScout/1.0 (contact: dealscout@example.com)"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        bindings = resp.json().get("results", {}).get("bindings", [])
        if not bindings:
            return None

        row = bindings[0]
        entity_uri = row.get("entity", {}).get("value", "")
        entity_label = row.get("entityLabel", {}).get("value", company_name)

        # Wikidata entity URI → URL
        wikidata_url = entity_uri.replace(
            "http://www.wikidata.org/entity/",
            "https://www.wikidata.org/wiki/",
        )

        # Extract year from inception datetime
        inception_raw = row.get("inception", {}).get("value", "")
        inception_year = inception_raw[:4] if inception_raw else None

        _log(f"Wikidata: matched '{entity_label}'")
        return {
            "source": "wikidata",
            "match_confidence": 1.0,
            "registered_name": entity_label,
            "inception_year": inception_year,
            "country": row.get("countryLabel", {}).get("value"),
            "website": row.get("website", {}).get("value"),
            "employee_count": row.get("employees", {}).get("value"),
            "wikidata_url": wikidata_url,
        }
    except Exception as exc:
        _log(f"Wikidata error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Function 3 — NewsAPI (PE-relevant filter, session cache)
# ---------------------------------------------------------------------------

PE_KEYWORDS = [
    "acqui", "merger", "invest", "funding", "raise", "round", "growth",
    "revenue", "profit", "expand", "partner", "launch", "contract", "win",
    "appoint", "ceo", "founder", "exit", "ipo", "valuation", "private equity",
    "venture", "strategic", "deal", "buyout",
]


def _is_pe_relevant(article: dict) -> bool:
    text = f"{article.get('title', '')} {article.get('description', '')}".lower()
    return any(kw in text for kw in PE_KEYWORDS)


def query_news(company_name: str, log_fn=None) -> list:
    """
    Fetch recent PE-relevant news about the company via NewsAPI.
    Free tier: 100 req/day. Results cached per name for the session.
    Returns [] if NEWS_API_KEY not set.
    """
    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        return []

    cache_key = company_name.lower().strip()
    if cache_key in _news_cache:
        return _news_cache[cache_key]

    try:
        from newsapi import NewsApiClient
        client = NewsApiClient(api_key=api_key)
        result = client.get_everything(
            q=f'"{company_name}"',
            language="en",
            sort_by="publishedAt",
            page_size=10,
        )
        articles = result.get("articles", [])
        relevant = [
            {
                "title": a.get("title", ""),
                "source": a.get("source", {}).get("name", ""),
                "published_at": a.get("publishedAt", ""),
                "url": a.get("url", ""),
                "description": a.get("description", ""),
            }
            for a in articles
            if _is_pe_relevant(a)
        ][:5]
        _log(f"NewsAPI: {len(relevant)} PE-relevant articles for '{company_name}'")
        _news_cache[cache_key] = relevant
        return relevant
    except Exception as exc:
        _log(f"NewsAPI error: {exc}")
        _news_cache[cache_key] = []
        return []


# ---------------------------------------------------------------------------
# Function 4 — Clearbit Logo (free, no key)
# ---------------------------------------------------------------------------

def get_company_logo_url(website: Optional[str]) -> Optional[str]:
    """Returns Clearbit logo CDN URL for a domain. Free, no key."""
    if not website:
        return None
    try:
        domain = urlparse(website).netloc or website
        domain = domain.replace("www.", "").rstrip("/")
        if not domain:
            return None
        return f"https://logo.clearbit.com/{domain}"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public convenience function
# ---------------------------------------------------------------------------

def enrich_company(
    company_name: str,
    country: Optional[str] = None,
    website: Optional[str] = None,
    log_fn=None,
) -> dict:
    """
    Run all registry sources for a company. Returns combined enrichment dict.
    Each source is skipped gracefully if the key is missing or an error occurs.
    """
    result = {
        "best_registry": None,
        "companies_house": None,
        "wikidata": None,
        "news": [],
        "logo_url": get_company_logo_url(website),
    }

    # Companies House: UK-registered companies only
    if country in ("United Kingdom", "UK", None):
        if os.getenv("COMPANIES_HOUSE_API_KEY", ""):
            result["companies_house"] = query_companies_house(company_name, log_fn=log_fn)

    # Wikidata: always try (free, no key)
    result["wikidata"] = query_wikidata(company_name, log_fn=log_fn)

    # News
    result["news"] = query_news(company_name, log_fn=log_fn)

    # Pick best registry result by confidence
    candidates = [
        r for r in [result["companies_house"], result["wikidata"]]
        if r and r.get("match_confidence", 0) > 0.8
    ]
    if candidates:
        result["best_registry"] = max(candidates, key=lambda r: r.get("match_confidence", 0))

    return result
