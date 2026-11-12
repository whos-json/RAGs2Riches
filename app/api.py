from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import llm as llm_mod
from app.config import Settings, get_settings
from app.db import Deal, Feedback, init_db, make_engine, session_factory
from app.ingest import ingest_xlsx
from app.portfolio import compute_portfolio
from app.schemas import EvaluateRequest
from app.workflow import build_graph, graph_spec, run_workflow

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

MAX_INGEST_BYTES = 50 * 1024 * 1024
MAX_CONCURRENT_RUNS = 4
EVENT_QUEUE_MAX = 256
QUEUE_POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
MAX_ERROR_CHARS = 300
MAX_UPLOAD_NAME_CHARS = 100
ZIP_MAGIC = b"PK\x03\x04"
UPLOAD_NAME_PATTERN = re.compile(r"[A-Za-z0-9 ._()-]+")
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
OUTCOMES = ("WON", "LOST", "DROPPED")


class IngestRequest(BaseModel):
    path: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional. The configured SOURCE_XLSX, or a .xlsx path inside INGEST_DIR. "
        "Relative paths are resolved against INGEST_DIR.",
    )


class FeedbackRequest(BaseModel):
    deal_id: str = Field(min_length=1, max_length=255)
    outcome: Optional[Literal["WON", "LOST", "DROPPED"]] = None
    useful: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("deal_id")
    @classmethod
    def _clean_deal_id(cls, value: str) -> str:
        cleaned = strip_control_chars(value)
        if not cleaned:
            raise ValueError("deal_id must not be blank")
        return cleaned

    @field_validator("note")
    @classmethod
    def _clean_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return strip_control_chars(value) or None

    @model_validator(mode="after")
    def _needs_content(self) -> "FeedbackRequest":
        if self.outcome is None and self.useful is None and self.note is None:
            raise ValueError("Provide at least one of outcome, useful or note")
        return self


class _RunAborted(Exception):
    """Raised inside the worker thread when the stream is closed or timed out."""


def _safe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:MAX_ERROR_CHARS]}"


def strip_control_chars(text: str) -> str:
    spaced = re.sub(r"[\t\r\n]+", " ", text)
    return CONTROL_CHARS.sub("", spaced).strip()


def clean_upload_name(raw: str) -> str:
    """Reduce a client-supplied filename to a safe `.xlsx` basename or raise 400."""
    name = re.split(r"[\\/]", raw)[-1].strip().rstrip(".")
    stem, dot, suffix = name.rpartition(".")
    if not name or not UPLOAD_NAME_PATTERN.fullmatch(name) or len(name) > MAX_UPLOAD_NAME_CHARS:
        raise HTTPException(status_code=400, detail="Invalid file name.")
    if not dot or suffix.lower() != "xlsx":
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")
    if not stem.strip(" .") or stem.split(".")[0].strip().upper() in WINDOWS_RESERVED_NAMES:
        raise HTTPException(status_code=400, detail="Invalid file name.")
    return name


def declared_upload_size(request: Request) -> int:
    header = request.headers.get("content-length")
    if header is None:
        raise HTTPException(status_code=411, detail="Content-Length is required.")
    if not header.isascii() or not header.isdigit():
        raise HTTPException(status_code=400, detail="Invalid Content-Length.")
    size = int(header)
    if size == 0:
        raise HTTPException(status_code=400, detail="The file is empty.")
    if size > MAX_INGEST_BYTES:
        raise HTTPException(status_code=413, detail="File is too large to ingest.")
    return size


def save_upload(name: str, body: bytes, ingest_dir: Path) -> Path:
    """Write `body` into `ingest_dir` under `name`, adding a numeric suffix if it already exists."""
    ingest_dir.mkdir(parents=True, exist_ok=True)
    root = ingest_dir.resolve()
    stem, suffix = name[: -len(".xlsx")], name[-len(".xlsx"):]
    for attempt in range(1000):
        candidate = root / (name if attempt == 0 else f"{stem}_{attempt}{suffix}")
        if candidate.resolve().parent != root:
            raise HTTPException(status_code=400, detail="Invalid file name.")
        try:
            with open(candidate, "xb") as handle:
                handle.write(body)
        except FileExistsError:
            continue
        return candidate
    raise HTTPException(status_code=409, detail="Too many files with that name.")


def resolve_ingest_path(requested: Optional[str], settings: Settings) -> Path:
    """Map a client-supplied ingest path to a file the server allows reading.

    Allowed: the configured SOURCE_XLSX (the default), or a .xlsx file inside
    INGEST_DIR. Traversal segments, UNC paths, NUL bytes and anything resolving
    (after symlinks) outside those locations are rejected.
    """
    source = Path(settings.source_xlsx).resolve()
    if not requested:
        candidate = source
    else:
        if "\x00" in requested:
            raise HTTPException(status_code=400, detail="Invalid path.")
        if requested.startswith(("\\\\", "//")):
            raise HTTPException(status_code=400, detail="Network paths are not allowed.")
        if ".." in re.split(r"[\\/]", requested):
            raise HTTPException(status_code=400, detail="Path traversal is not allowed.")
        ingest_dir = Path(settings.ingest_dir).resolve()
        raw = Path(requested)
        candidate = (raw if raw.is_absolute() else ingest_dir / raw).resolve()
        if candidate != source and not candidate.is_relative_to(ingest_dir):
            raise HTTPException(
                status_code=403,
                detail="Path must be the configured SOURCE_XLSX or inside the ingest directory.",
            )
    if candidate.suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if candidate.stat().st_size > MAX_INGEST_BYTES:
        raise HTTPException(status_code=413, detail="File is too large to ingest.")
    return candidate


def _checked_selection(req: EvaluateRequest) -> dict:
    """LLM selection from the request. Only provider and a validated model name pass through.

    Base URLs are never read from the request; they come from server settings in `llm.py`.
    """
    selection = req.llm.model_dump()
    try:
        selection["model"] = llm_mod.validate_model_name(selection.get("model"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return selection


def create_app() -> FastAPI:
    settings = get_settings()
    engine = make_engine()
    init_db(engine)
    sessions = session_factory(engine)
    graph = build_graph(sessions)
    run_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
    ingest_lock = threading.Lock()
    run_deadline_seconds = settings.llm_timeout_seconds * 4 + 30

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        with sessions() as session:
            count = session.scalar(select(func.count()).select_from(Deal))
        if not count and Path(settings.source_xlsx).exists():
            ingest_xlsx(settings.source_xlsx, sessions)
        yield

    app = FastAPI(title="RAGS2Riches", lifespan=lifespan)

    # CORS is intentionally NOT enabled: the UI is served from this same origin, so
    # browsers block other sites from reading responses or sending JSON POSTs.
    # The host check below additionally defeats DNS-rebinding against a local server.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    # Endpoints are plain `def`, so FastAPI runs them in its threadpool. Blocking
    # work (SQL, provider probes, LLM calls) therefore never stalls the event loop.

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/meta")
    def meta() -> dict:
        with sessions() as session:
            industries = sorted(
                {i for i in session.scalars(select(Deal.industry).distinct()) if i}
            )
            count = session.scalar(select(func.count()).select_from(Deal))
        return {
            "providers": llm_mod.provider_catalog(),  # probes are cached for a few seconds
            "industries": industries,
            "deal_count": count,
            "has_data": bool(count),
            "default_llm": {
                "provider": settings.default_llm_provider,
                "model": settings.default_llm_model,
            },
        }

    @app.get("/api/portfolio")
    def portfolio() -> dict:
        with sessions() as session:
            all_deals = session.scalars(select(Deal)).all()
        return compute_portfolio(list(all_deals))

    @app.get("/api/deals")
    def deals(limit: int = Query(default=200, ge=1, le=1000)) -> list[dict]:
        with sessions() as session:
            rows = session.scalars(select(Deal).order_by(Deal.deal_name).limit(limit)).all()
        return [
            {
                "deal_name": d.deal_name,
                "industry": d.industry,
                "size_sqft": d.size_sqft,
                "lease_term_months": d.lease_term_months,
                "gross_signing_rent_psf": d.gross_signing_rent_psf,
                "property_name": d.property_name,
                "lead_agent": d.lead_agent,
                "actual_gross_fee_sgd": d.gross_fee_sgd,
            }
            for d in rows
        ]

    def run_ingest(path: Path, failure_detail: Optional[str] = None) -> dict:
        if not ingest_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="An ingest is already running.")
        try:
            result = ingest_xlsx(str(path), sessions)
        except Exception as exc:
            logger.exception("Ingest failed for %s", path)
            detail = failure_detail or f"Workbook could not be ingested ({type(exc).__name__})."
            raise HTTPException(status_code=422, detail=detail) from exc
        finally:
            ingest_lock.release()
        return {**result, "source": path.name}

    @app.post("/api/ingest")
    def ingest(req: IngestRequest) -> dict:
        return run_ingest(resolve_ingest_path(req.path, settings))

    @app.post("/api/upload")
    async def upload(request: Request, filename: str = Query(min_length=1, max_length=255)) -> dict:
        name = clean_upload_name(filename)
        declared_upload_size(request)
        body = await request.body()
        if len(body) > MAX_INGEST_BYTES:
            raise HTTPException(status_code=413, detail="File is too large to ingest.")
        if not body.startswith(ZIP_MAGIC):
            raise HTTPException(status_code=400, detail="The file is not a valid .xlsx workbook.")
        saved = await run_in_threadpool(save_upload, name, body, Path(settings.ingest_dir))
        try:
            result = await run_in_threadpool(
                run_ingest, saved, "The workbook could not be read. Check that it is a leasing export in .xlsx format."
            )
        except HTTPException:
            saved.unlink(missing_ok=True)
            raise
        return result

    @app.post("/api/feedback")
    def feedback(req: FeedbackRequest) -> dict:
        with sessions() as session:
            session.add(
                Feedback(deal_id=req.deal_id, outcome=req.outcome, useful=req.useful, note=req.note)
            )
            session.commit()
        return {"saved": True}

    @app.get("/api/feedback/summary")
    def feedback_summary() -> dict:
        with sessions() as session:
            total = session.scalar(select(func.count()).select_from(Feedback)) or 0
            by_outcome = dict(
                session.execute(
                    select(Feedback.outcome, func.count()).where(Feedback.outcome.is_not(None)).group_by(Feedback.outcome)
                ).all()
            )
            useful = dict(
                session.execute(
                    select(Feedback.useful, func.count()).where(Feedback.useful.is_not(None)).group_by(Feedback.useful)
                ).all()
            )
        return {
            "total": total,
            "by_outcome": {name: by_outcome.get(name, 0) for name in OUTCOMES},
            "useful_yes": useful.get(True, 0),
            "useful_no": useful.get(False, 0),
        }

    @app.get("/api/workflow")
    def workflow() -> dict:
        return graph_spec(graph)

    @app.post("/api/evaluate")
    def evaluate(req: EvaluateRequest) -> dict:
        selection = _checked_selection(req)
        if not run_slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Too many evaluations running; retry shortly.")
        try:
            return run_workflow(graph, req.deal.model_dump(), selection)
        finally:
            run_slots.release()

    @app.post("/api/evaluate/stream")
    def evaluate_stream(req: EvaluateRequest) -> StreamingResponse:
        selection = _checked_selection(req)
        deal = req.deal.model_dump()
        if not run_slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Too many evaluations running; retry shortly.")

        # Bounded queue: a slow or vanished client cannot make the worker buffer without limit.
        events: queue.Queue = queue.Queue(maxsize=EVENT_QUEUE_MAX)
        closed = threading.Event()
        deadline = time.monotonic() + run_deadline_seconds

        def emit(event: Any) -> None:
            # Called from graph nodes in the worker thread. Raising aborts the run at
            # the next node boundary once the client is gone or the deadline passed.
            while True:
                if closed.is_set() or time.monotonic() > deadline:
                    raise _RunAborted()
                try:
                    events.put(event, timeout=0.5)
                    return
                except queue.Full:
                    continue

        def worker() -> None:
            try:
                scorecard = run_workflow(graph, deal, selection, emit=emit)
                emit({"type": "run_complete", "scorecard": scorecard})
            except _RunAborted:
                pass
            except Exception as exc:
                logger.exception("Evaluation failed")
                try:
                    emit({"type": "run_error", "error": _safe_error(exc)})
                except _RunAborted:
                    pass
            finally:
                run_slots.release()
                try:
                    events.put(None, timeout=1.0)  # end-of-stream marker
                except queue.Full:
                    pass  # consumer also stops once the thread is dead and the queue is empty

        thread = threading.Thread(target=worker, name="evaluate-stream", daemon=True)
        try:
            thread.start()
        except Exception:
            run_slots.release()
            raise HTTPException(status_code=503, detail="Could not start evaluation.")

        def encode(event: dict) -> str:
            try:
                return f"data: {json.dumps(event, default=str)}\n\n"
            except Exception as exc:
                error = {"type": "run_error", "error": _safe_error(exc)}
                return f"data: {json.dumps(error)}\n\n"

        def stream():
            last_sent = time.monotonic()
            try:
                while True:
                    try:
                        event = events.get(timeout=QUEUE_POLL_SECONDS)
                    except queue.Empty:
                        now = time.monotonic()
                        if not thread.is_alive() and events.empty():
                            return
                        if now > deadline:
                            yield encode({"type": "run_error", "error": "TimeoutError: evaluation timed out"})
                            return
                        if now - last_sent >= HEARTBEAT_SECONDS:
                            last_sent = now
                            yield ": keepalive\n\n"
                        continue
                    if event is None:
                        return
                    last_sent = time.monotonic()
                    yield encode(event)
            finally:
                # Runs on normal end, errors, and when the client disconnects (generator closed).
                closed.set()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
