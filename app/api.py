from __future__ import annotations

import json
import queue
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app import llm as llm_mod
from app.config import get_settings
from app.db import Deal, init_db, make_engine, session_factory
from app.ingest import ingest_xlsx
from app.schemas import EvaluateRequest
from app.workflow import build_graph, graph_spec, run_workflow

STATIC_DIR = Path(__file__).resolve().parent / "static"


class IngestRequest(BaseModel):
    path: Optional[str] = None


def create_app() -> FastAPI:
    settings = get_settings()
    engine = make_engine()
    init_db(engine)
    sessions = session_factory(engine)
    graph = build_graph(sessions)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        with sessions() as session:
            count = session.scalar(select(func.count()).select_from(Deal))
        if not count and Path(settings.source_xlsx).exists():
            ingest_xlsx(settings.source_xlsx, sessions)
        yield

    app = FastAPI(title="RAGS2Riches", lifespan=lifespan)

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
            "providers": llm_mod.provider_catalog(),
            "industries": industries,
            "deal_count": count,
            "default_llm": {
                "provider": settings.default_llm_provider,
                "model": settings.default_llm_model,
            },
        }

    @app.get("/api/deals")
    def deals(limit: int = 200) -> list[dict]:
        with sessions() as session:
            rows = session.scalars(select(Deal).order_by(Deal.deal_name).limit(min(limit, 1000))).all()
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

    @app.post("/api/ingest")
    def ingest(req: IngestRequest) -> dict:
        path = req.path or settings.source_xlsx
        if not path.lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")
        if not Path(path).exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        return ingest_xlsx(path, sessions)

    @app.get("/api/workflow")
    def workflow() -> dict:
        return graph_spec(graph)

    @app.post("/api/evaluate")
    def evaluate(req: EvaluateRequest) -> dict:
        return run_workflow(graph, req.deal.model_dump(), req.llm.model_dump())

    @app.post("/api/evaluate/stream")
    def evaluate_stream(req: EvaluateRequest) -> StreamingResponse:
        events: queue.Queue = queue.Queue()

        def worker() -> None:
            try:
                scorecard = run_workflow(
                    graph, req.deal.model_dump(), req.llm.model_dump(), emit=events.put
                )
                events.put({"type": "run_complete", "scorecard": scorecard})
            except Exception as exc:
                events.put({"type": "run_error", "error": f"{type(exc).__name__}: {exc}"})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def stream():
            while True:
                event = events.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
