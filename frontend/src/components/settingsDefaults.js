export const GOOGLE_MODELS = [
  'gemini-3-flash-preview',
  'gemini-2.5-flash',
]

export const OPENROUTER_MODELS = [
  'meta-llama/llama-3.3-70b-instruct:free',
  'deepseek/deepseek-r1:free',
  'nvidia/nemotron-3-super-120b-a12b:free',
]

export const DEFAULTS = {
  temperature: 0.2,
  max_tokens_brief: 3000,
  max_tokens_json: 2000,
  max_tokens_profile: 2500,
  max_tokens_outreach: 500,
  system_prompt:
    'You are a structured data assistant. When asked to return JSON, return ONLY valid JSON with no markdown fences, no preamble, and no explanation. When asked to return markdown, return only markdown.',
  tavily_max_results: 5,
  google_model: 'gemini-3-flash-preview',
  google_use_search: true,
  openrouter_model: 'meta-llama/llama-3.3-70b-instruct:free',
  search_provider: 'tavily',
  source_scraping_enabled: true,
  contact_enrichment_enabled: true,
  verification_enabled: true,
  verification_tavily_enabled: true,
  verification_citations_enabled: true,
  verification_tavily_max_calls: 20,
}
