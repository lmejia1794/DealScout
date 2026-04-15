from pydantic import BaseModel
from typing import Dict, Literal, Optional


class ResearchRequest(BaseModel):
    thesis: str
    settings: Optional[dict] = None


class TestRequest(BaseModel):
    thesis: str
    step: Literal["sector_brief", "conferences", "companies"] = "sector_brief"


class Conference(BaseModel):
    name: str
    date: str
    location: str
    description: str
    website: Optional[str] = None
    estimated_cost: str
    notable_attendees: list[str]
    relevance: str


class Company(BaseModel):
    name: str
    country: str
    hq_city: Optional[str] = None
    founded: Optional[int] = None
    estimated_arr: Optional[str] = None
    employee_count: Optional[str] = None
    ownership: Optional[str] = None
    description: str
    website: Optional[str] = None
    fit_score: int
    fit_rationale: str
    signals: list[str]


class ResearchResponse(BaseModel):
    sector_brief: str
    conferences: list[Conference]
    companies: list[Company]


# ---------------------------------------------------------------------------
# Phase 2 models
# ---------------------------------------------------------------------------

class ContactInfo(BaseModel):
    email: Optional[str] = None
    email_confidence: Optional[str] = None   # "high" | "medium" | "low"
    email_source: Optional[str] = None       # "website" | "smtp_verified" | "pattern_unverified" | "web_search"
    phone: Optional[str] = None
    phone_confidence: Optional[str] = None
    phone_source: Optional[str] = None
    enrichment_notes: Optional[str] = None


class DecisionMaker(BaseModel):
    name: str
    title: str
    linkedin_url: Optional[str] = None
    notes: Optional[str] = None
    contact: Optional[ContactInfo] = None


class CompanyProfile(BaseModel):
    business_model: str            # markdown
    financials: str                # markdown
    recent_news: str               # markdown
    competitive_positioning: str   # markdown
    fit_assessment: str            # markdown
    hq_country: str                # full English country name e.g. "Germany"
    service_countries: list[str]   # full English country names including HQ
    decision_makers: list[DecisionMaker]


class ProfileRequest(BaseModel):
    company: Company
    thesis: str
    settings: Optional[dict] = None


class OutreachRequest(BaseModel):
    company: Company
    profile: CompanyProfile
    thesis: str
    settings: Optional[dict] = None


class OutreachResponse(BaseModel):
    subject: str
    body: str   # plain text, not markdown


# ---------------------------------------------------------------------------
# Phase 3 models
# ---------------------------------------------------------------------------

class ComparableTransaction(BaseModel):
    target: str
    acquirer: str
    year: Optional[int] = None
    deal_type: str                      # "PE Buyout" | "Strategic Acquisition" | "Growth Investment"
    reported_ev: Optional[str] = None   # e.g. "€120M" or null if undisclosed
    reported_multiple: Optional[str] = None  # e.g. "6× ARR" or null
    target_description: str             # 1 sentence
    relevance: str                      # 1 sentence


class ComparablesRequest(BaseModel):
    thesis: str
    sector_brief: str
    settings: Optional[dict] = None


class ComparablesResponse(BaseModel):
    transactions: list[ComparableTransaction]


# ---------------------------------------------------------------------------
# Verification models
# ---------------------------------------------------------------------------

VerificationStatus = Literal["verified", "contradicted", "unverifiable", "inferred", "pending"]


class Verification(BaseModel):
    status: VerificationStatus
    source_url: Optional[str] = None
    source_snippet: Optional[str] = None
    checked_query: Optional[str] = None
    citation_url: Optional[str] = None
    citation_note: Optional[str] = None
    human_override: Optional[Literal["confirmed", "disputed"]] = None
    claim: Optional[str] = None          # the claim text that was (or can be) verified
    corrected_value: Optional[str] = None  # replacement value when status=contradicted


class VerifiedCompany(BaseModel):
    company: Company
    verifications: Dict[str, Verification] = {}
    overall_confidence: Optional[Literal["high", "medium", "low"]] = None


class VerifiedConference(BaseModel):
    conference: Conference
    verifications: Dict[str, Verification] = {}
    overall_confidence: Optional[Literal["high", "medium", "low"]] = None


class SectorBriefVerification(BaseModel):
    claims: list = []
    overall_confidence: Optional[Literal["high", "medium", "low"]] = None


# ---------------------------------------------------------------------------
# On-demand field verification
# ---------------------------------------------------------------------------

class FieldVerifyRequest(BaseModel):
    entity_name: str
    entity_type: str          # "company" | "conference" | "sector_claim"
    field_name: str
    claim: str
    context: Optional[str] = None
    settings: Optional[dict] = None


class FieldVerifyResponse(BaseModel):
    field_name: str
    verification: Verification
    tavily_used: bool = False


class SettingsModel(BaseModel):
    temperature: float = 0.2
    max_tokens_brief: int = 3000
    max_tokens_json: int = 2000
    max_tokens_profile: int = 2500
    max_tokens_outreach: int = 500
    system_prompt: str = (
        "You are a structured data assistant. "
        "When asked to return JSON, return ONLY valid JSON with no markdown fences, "
        "no preamble, and no explanation. "
        "When asked to return markdown, return only markdown."
    )
    tavily_max_results: int = 5
    google_model: str = "gemini-3-flash-preview"
    google_use_search: bool = True
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    source_scraping_enabled: bool = True
    contact_enrichment_enabled: bool = True
    verification_enabled: bool = True
    verification_tavily_enabled: bool = True
    verification_citations_enabled: bool = True
    verification_tavily_max_calls: int = 20
