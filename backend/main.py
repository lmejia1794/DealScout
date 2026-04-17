import asyncio
import json
import logging
import os
import queue
import threading
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

load_dotenv()

from models import ResearchRequest, TestRequest, StepRequest, ProfileRequest, OutreachRequest, ComparablesRequest, FieldVerifyRequest, FieldVerifyResponse, Verification
from research import generate_sector_brief, generate_conferences, generate_companies, run_research
from profile import generate_profile, generate_outreach, _hunter_email, _enrich_decision_makers
from comparables import generate_comparables

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Run logger — writes all log_fn messages to last_run.log, overwritten each run
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(os.path.dirname(__file__), "last_run.log")
_log_lock = threading.Lock()


def _wrap_log_fn(inner_log_fn, run_label: str):
    """
    Wraps an existing log_fn so that every message is:
    1. Written to last_run.log (opened in write mode — overwriting the previous run).
    2. Forwarded to inner_log_fn (which feeds the SSE queue).

    Returns (wrapped_log_fn, close_fn).  Call close_fn() when the run ends.
    """
    _file_handle = [None]

    with _log_lock:
        try:
            fh = open(_LOG_PATH, "w", encoding="utf-8", buffering=1)
            fh.write(f"=== DealScout run: {run_label} | {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
            _file_handle[0] = fh
        except Exception as exc:
            logger.warning("Could not open last_run.log: %s", exc)

    def wrapped(msg: str):
        fh = _file_handle[0]
        if fh:
            ts = time.strftime("%H:%M:%S")
            try:
                fh.write(f"[{ts}] {msg}\n")
            except Exception:
                pass
        inner_log_fn(msg)

    def close():
        fh = _file_handle[0]
        if fh:
            try:
                fh.write(f"\n=== run ended {time.strftime('%H:%M:%S')} ===\n")
                fh.close()
            except Exception:
                pass

    return wrapped, close


# ---------------------------------------------------------------------------
# Job registry — persistent event buffer so clients can reconnect after refresh
# ---------------------------------------------------------------------------

_job_registry: dict = {}   # job_id -> {buffer, status, lock, created_at}
_registry_lock = threading.Lock()
_JOB_TTL = 7200  # 2 hours


def _create_job() -> tuple:
    job_id = str(uuid.uuid4())
    job = {"buffer": [], "status": "running", "created_at": time.time(), "lock": threading.Lock()}
    with _registry_lock:
        _job_registry[job_id] = job
        cutoff = time.time() - _JOB_TTL
        for jid in [k for k, v in _job_registry.items() if v["created_at"] < cutoff]:
            del _job_registry[jid]
    return job_id, job


def _append_job_event(job: dict, event: dict) -> None:
    with job["lock"]:
        job["buffer"].append(event)


async def _poll_job_stream(job: dict, from_index: int = 0):
    """Yield SSE-formatted strings from job buffer starting at from_index."""
    idx = from_index
    while True:
        with job["lock"]:
            snapshot = list(job["buffer"][idx:])
            status = job["status"]
        for event in snapshot:
            yield f"data: {json.dumps(event)}\n\n"
            idx += 1
        if status in ("done", "error") and not snapshot:
            break
        await asyncio.sleep(0.1)


app = FastAPI(title="DealScout API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://dealscout-1.onrender.com",
    ],
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

    job_id, job = _create_job()

    def run():
        def _queue_log(msg):
            _append_job_event(job, {"type": "log", "message": msg})

        log_fn, close_log = _wrap_log_fn(_queue_log, f"research: {req.thesis[:60]}")

        def phase_fn(phase, data):
            _append_job_event(job, {"type": "phase_result", "phase": phase, "data": data})

        final_status = "error"
        try:
            result = run_research(req.thesis, settings=req.settings, log_fn=log_fn, phase_fn=phase_fn)
            _append_job_event(job, {"type": "result", "data": result})
            final_status = "done"
        except RuntimeError as e:
            log_fn(f"ERROR: {e}")
            _append_job_event(job, {"type": "error", "message": str(e)})
        except Exception as e:
            logger.exception("Unexpected error in run_research")
            log_fn(f"UNEXPECTED ERROR: {type(e).__name__}: {e}")
            _append_job_event(job, {"type": "error", "message": f"Unexpected server error: {type(e).__name__}: {e}"})
        finally:
            close_log()
            with job["lock"]:
                job["status"] = final_status

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    async def event_stream():
        yield f"data: {json.dumps({'type': 'job_id', 'job_id': job_id})}\n\n"
        async for chunk in _poll_job_stream(job):
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/research/jobs/{job_id}")
async def reconnect_research_job(job_id: str):
    """Reconnect to a running or completed research job after a page refresh."""
    job = _job_registry.get(job_id)
    if not job:
        return JSONResponse({"error": "job_not_found"}, status_code=404)

    async def stream():
        # Replay phase/result events from current buffer (skip logs to avoid duplication)
        with job["lock"]:
            replay = [e for e in job["buffer"] if e.get("type") in ("phase_result", "result", "error")]
            live_start = len(job["buffer"])

        for event in replay:
            yield f"data: {json.dumps(event)}\n\n"

        # Continue streaming new events from where the buffer was at reconnect time
        async for chunk in _poll_job_stream(job, from_index=live_start):
            yield chunk

    return StreamingResponse(stream(), media_type="text/event-stream")


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
# Regenerate a single pipeline step with existing context (SSE)
# ---------------------------------------------------------------------------

@app.post("/api/research/step")
async def research_step(req: StepRequest):
    """
    Regenerate one step using the current context.
    POST /api/research/step
    { "step": "sector_brief"|"conferences"|"companies", "thesis": "...",
      "sector_brief": "...", "settings": {...} }
    Returns same SSE format as /api/research/run.
    """
    log_q: queue.Queue = queue.Queue()
    result_holder: dict = {}

    def run():
        def log_fn(msg):
            log_q.put({"type": "log", "message": msg})
        try:
            s = req.settings or {}
            if req.step == "sector_brief":
                data = generate_sector_brief(req.thesis, log_fn=log_fn, settings=s)
                result_holder["data"] = {"sector_brief": data, "sector_brief_verification": None}
            elif req.step == "conferences":
                data, _ = generate_conferences(req.thesis, sector_brief=req.sector_brief, log_fn=log_fn, settings=s)
                result_holder["data"] = {"conferences": data}
            else:  # companies
                data, _ = generate_companies(req.thesis, sector_brief=req.sector_brief, log_fn=log_fn, settings=s)
                result_holder["data"] = {"companies": data}
        except Exception as e:
            logger.exception("Error regenerating step %s", req.step)
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
        def _queue_log(msg):
            log_q.put({"type": "log", "message": msg})
        company_name = req.company.name if hasattr(req.company, 'name') else 'unknown'
        log_fn, close_log = _wrap_log_fn(_queue_log, f"profile: {company_name}")
        try:
            data = generate_profile(req.company.model_dump(), req.thesis, log_fn=log_fn, settings=req.settings)
            result_holder["data"] = data
        except Exception as e:
            logger.exception("Error generating company profile")
            log_fn(f"ERROR: {type(e).__name__}: {e}")
            result_holder["error"] = str(e)
        finally:
            close_log()
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
            transactions = generate_comparables(req.thesis, req.sector_brief, log_fn=log_fn, settings=req.settings)
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
    search_provider = _settings.get('search_provider', 'duckduckgo')

    try:
        v_dict, tavily_used = verify_field(
            entity_name=req.entity_name,
            field_name=req.field_name,
            claim=req.claim,
            context=req.context or "",
            use_tavily=use_tavily,
            search_provider=search_provider,
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
