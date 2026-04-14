import asyncio
import json
import logging
import queue
import threading

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv()

from models import ResearchRequest, TestRequest, ProfileRequest, OutreachRequest, ComparablesRequest, FieldVerifyRequest, FieldVerifyResponse, Verification
from research import generate_sector_brief, generate_conferences, generate_companies, run_research
from profile import generate_profile, generate_outreach, _hunter_email, _enrich_decision_makers
from comparables import generate_comparables

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="DealScout API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/research")
async def research(req: ResearchRequest):
    if not req.thesis.strip():
        async def _err():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Thesis cannot be empty.'})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    log_q: queue.Queue = queue.Queue()
    result_holder: dict = {}

    def run():
        def log_fn(msg):
            log_q.put({"type": "log", "message": msg})

        try:
            result = run_research(req.thesis, known_companies=req.known_companies, settings=req.settings, log_fn=log_fn)
            result_holder["data"] = result
        except RuntimeError as e:
            result_holder["error"] = str(e)
        except Exception as e:
            logger.exception("Unexpected error in run_research")
            result_holder["error"] = "An unexpected error occurred on the server."
        finally:
            log_q.put(None)  # sentinel — pipeline finished

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    async def event_stream():
        while True:
            try:
                item = log_q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue

            if item is None:
                break  # pipeline done
            yield f"data: {json.dumps(item)}\n\n"

        thread.join(timeout=5)

        if "error" in result_holder:
            yield f"data: {json.dumps({'type': 'error', 'message': result_holder['error']})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'result', 'data': result_holder['data']})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/test")
async def test_step(req: TestRequest):
    """
    Run a single pipeline step in isolation for debugging.

    POST /api/test
    { "thesis": "...", "step": "sector_brief" | "conferences" | "companies" }

    Returns the same SSE stream as /api/research but for one step only.
    For conferences/companies a blank sector_brief stub is used so the step
    can run without the full pipeline.
    """
    log_q: queue.Queue = queue.Queue()
    result_holder: dict = {}

    def run():
        def log_fn(msg):
            log_q.put({"type": "log", "message": msg})

        try:
            if req.step == "sector_brief":
                data = generate_sector_brief(req.thesis, log_fn=log_fn)
                result_holder["data"] = {"sector_brief": data, "conferences": [], "companies": []}
            elif req.step == "conferences":
                data, _ = generate_conferences(req.thesis, sector_brief="", log_fn=log_fn)
                result_holder["data"] = {"sector_brief": "", "conferences": data, "companies": []}
            else:  # companies
                data, _ = generate_companies(req.thesis, sector_brief="", log_fn=log_fn)
                result_holder["data"] = {"sector_brief": "", "conferences": [], "companies": data}
        except Exception as e:
            logger.exception("Error in test step %s", req.step)
            result_holder["error"] = str(e)
        finally:
            log_q.put(None)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    async def event_stream():
        while True:
            try:
                item = log_q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

        thread.join(timeout=5)

        if "error" in result_holder:
            yield f"data: {json.dumps({'type': 'error', 'message': result_holder['error']})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'result', 'data': result_holder['data']})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Phase 2 — Company profile (SSE streaming)
# ---------------------------------------------------------------------------

@app.post("/api/company/profile")
async def company_profile(req: ProfileRequest):
    log_q: queue.Queue = queue.Queue()
    result_holder: dict = {}

    def run():
        def log_fn(msg):
            log_q.put({"type": "log", "message": msg})
        try:
            data = generate_profile(req.company.model_dump(), req.thesis, log_fn=log_fn, settings=req.settings)
            result_holder["data"] = data
        except Exception as e:
            logger.exception("Error generating company profile")
            result_holder["error"] = str(e)
        finally:
            log_q.put(None)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    async def event_stream():
        while True:
            try:
                item = log_q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

        thread.join(timeout=5)

        if "error" in result_holder:
            yield f"data: {json.dumps({'type': 'error', 'message': result_holder['error']})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'result', 'data': result_holder['data']})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Phase 2 — Outreach email (standard JSON, fast)
# ---------------------------------------------------------------------------

@app.get("/api/test/hunter")
async def test_hunter(domain: str, name: str):
    """
    Quick smoke-test for Hunter.io integration.
    Example: GET /api/test/hunter?domain=stripe.com&name=Patrick+Collison
    """
    import os
    key = os.getenv("HUNTER_API_KEY", "")
    if not key:
        return {"status": "error", "message": "HUNTER_API_KEY not set in .env"}
    email = _hunter_email(domain, name)
    if email:
        return {"status": "ok", "email": email}
    return {"status": "not_found", "message": f"No email found for '{name}' at {domain}"}


@app.post("/api/company/outreach")
async def company_outreach(req: OutreachRequest):
    try:
        result = generate_outreach(
            req.company.model_dump(),
            req.profile.model_dump(),
            req.thesis,
        )
        return result
    except Exception as e:
        logger.exception("Error generating outreach")
        return {"subject": "", "body": f"Error: {e}"}


# ---------------------------------------------------------------------------
# Phase 3 — Comparable transactions
# ---------------------------------------------------------------------------

@app.post("/api/comparables")
async def comparables(req: ComparablesRequest):
    q: queue.Queue = queue.Queue()

    def _run():
        def log_fn(msg):
            q.put({"type": "log", "message": msg})
        try:
            transactions = generate_comparables(req.thesis, req.sector_brief, log_fn=log_fn)
            q.put({"type": "result", "data": {"transactions": transactions}})
        except Exception as e:
            logger.exception("Error generating comparables")
            q.put({"type": "error", "message": str(e)})
        finally:
            q.put(None)

    threading.Thread(target=_run, daemon=True).start()

    async def _stream():
        loop = asyncio.get_event_loop()
        while True:
            event = await loop.run_in_executor(None, q.get)
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# On-demand field verification (fast JSON — not SSE)
# ---------------------------------------------------------------------------

@app.post("/api/verify/field", response_model=FieldVerifyResponse)
async def verify_field_endpoint(req: FieldVerifyRequest):
    from verification import verify_field, TAVILY_ENABLED

    _settings = req.settings or {}
    use_tavily = bool(_settings.get('verification_tavily_enabled', TAVILY_ENABLED))

    try:
        v_dict, tavily_used = verify_field(
            entity_name=req.entity_name,
            field_name=req.field_name,
            claim=req.claim,
            context=req.context or "",
            use_tavily=use_tavily,
        )
        return FieldVerifyResponse(
            field_name=req.field_name,
            verification=Verification(**{k: val for k, val in v_dict.items() if k in Verification.model_fields}),
            tavily_used=tavily_used,
        )
    except Exception as e:
        logger.exception("Error in verify_field")
        return FieldVerifyResponse(
            field_name=req.field_name,
            verification=Verification(status="unverifiable", citation_note=str(e)),
            tavily_used=False,
        )
