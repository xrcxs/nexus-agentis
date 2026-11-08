"""FastAPI application for NEXUS//AGENTIS with resumable SSE, request size guards, and OpenAPI docs."""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from backend.app.config import Settings, get_settings
from backend.graph.workflow import RunOrchestrator
from backend.models.schemas import (
    CreateRunRequest,
    ErrorResponse,
    HumanDecisionRequest,
    LedgerVerifyResponse,
    RunDetail,
    RunStatus,
    RunSummary,
)
from backend.services.database import Database


class SSEHub:
    """In-memory pub/sub hub paired with SQLite event persistence for resumable SSE."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    def publish(self, run_id: str, event_dict: dict[str, Any]) -> None:
        queues = self._subscribers.get(run_id)
        if not queues:
            return
        for q in list(queues):
            try:
                q.put_nowait(event_dict)
            except asyncio.QueueFull:
                pass

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(run_id, set()).add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._subscribers.get(run_id)
        if queues and q in queues:
            queues.remove(q)
            if not queues:
                self._subscribers.pop(run_id, None)


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    settings = custom_settings or get_settings()
    db = Database(settings.database_path, settings.ledger_secret)
    sse_hub = SSEHub()
    orchestrator = RunOrchestrator(
        settings=settings,
        db=db,
        on_event=sse_hub.publish,
    )

    app = FastAPI(
        title="NEXUS//AGENTIS API",
        description=(
            "Autonomous multi-agent research system powered by LangGraph, Groq, and Tavily "
            "with claim-level entailment verification, human-in-the-loop checkpoint interrupts, "
            "and a tamper-evident SHA-256 + HMAC-SHA256 event ledger."
        ),
        version="1.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.state.settings = settings
    app.state.db = db
    app.state.sse_hub = sse_hub
    app.state.orchestrator = orchestrator

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID", "Accept"],
    )

    @app.middleware("http")
    async def enforce_request_size_limit(request: Request, call_next: Any) -> Any:
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > settings.max_request_bytes:
                err = ErrorResponse(
                    error_code="PAYLOAD_TOO_LARGE",
                    message=f"Request body exceeds maximum size of {settings.max_request_bytes} bytes.",
                )
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content=err.model_dump(),
                )
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "error_code" in detail:
            payload = detail
        else:
            payload = ErrorResponse(
                error_code=f"HTTP_{exc.status_code}",
                message=str(detail),
            ).model_dump()
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        err = ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Request payload failed schema validation.",
            details={"errors": exc.errors()},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=err.model_dump(),
        )

    @app.get("/health", tags=["system"])
    async def get_health() -> dict[str, Any]:
        runs = db.list_runs(limit=1)
        return {
            "status": "ok",
            "service": "nexus-agentis",
            "version": "1.0.0",
            "model": settings.groq_model,
            "active_runs": orchestrator.active_run_count,
            "max_concurrent_runs": settings.max_concurrent_runs,
            "database_connected": isinstance(runs, list),
            "groq_key_configured": bool(settings.groq_api_key),
            "tavily_key_configured": bool(settings.tavily_api_key),
            "stub_mode": settings.stub_external_apis,
        }

    @app.post(
        "/runs",
        response_model=RunSummary,
        status_code=status.HTTP_201_CREATED,
        tags=["runs"],
    )
    async def create_run(
        req: CreateRunRequest,
        wait_for_interrupt: bool = Query(
            default=False,
            description="If true, await execution until human_gate interrupt or completion before returning.",
        ),
    ) -> RunSummary:
        if orchestrator.active_run_count >= settings.max_concurrent_runs:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=ErrorResponse(
                    error_code="MAX_CONCURRENT_RUNS_EXCEEDED",
                    message=f"Server is already executing the maximum of {settings.max_concurrent_runs} concurrent runs.",
                ).model_dump(),
            )

        budget = min(req.token_budget, settings.max_token_budget)
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        summary = db.create_run(
            run_id=run_id,
            question=req.question,
            token_budget=budget,
            max_loops=req.max_loops,
            support_threshold=req.support_threshold,
        )

        if wait_for_interrupt:
            await orchestrator.execute_run(run_id)
            updated = db.get_run_summary(run_id)
            assert updated is not None
            return updated

        task = asyncio.create_task(orchestrator.execute_run(run_id))
        orchestrator._active_tasks[run_id] = task
        task.add_done_callback(lambda _: orchestrator._active_tasks.pop(run_id, None))
        return summary

    @app.get("/runs", response_model=list[RunSummary], tags=["runs"])
    async def list_runs(limit: int = Query(default=50, ge=1, le=200)) -> list[RunSummary]:
        return db.list_runs(limit=limit)

    @app.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"])
    async def get_run(run_id: str) -> RunDetail:
        detail = db.get_run_detail(run_id)
        if detail is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error_code="RUN_NOT_FOUND",
                    message=f"Run '{run_id}' does not exist.",
                ).model_dump(),
            )
        return detail

    @app.get("/runs/{run_id}/events", tags=["runs"])
    async def stream_run_events(
        run_id: str,
        request: Request,
        last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
        last_event_id_query: int | None = Query(default=None, alias="last_event_id", ge=0),
    ) -> StreamingResponse:
        summary = db.get_run_summary(run_id)
        if summary is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error_code="RUN_NOT_FOUND",
                    message=f"Run '{run_id}' does not exist.",
                ).model_dump(),
            )

        resume_id = 0
        if last_event_id_header and last_event_id_header.strip().isdigit():
            resume_id = int(last_event_id_header.strip())
        elif last_event_id_query is not None:
            resume_id = last_event_id_query

        async def event_generator() -> AsyncIterator[str]:
            seen_id = resume_id
            queue = sse_hub.subscribe(run_id)
            try:
                backlog = db.get_events_since(run_id, last_event_id=seen_id)
                for ev in backlog:
                    seen_id = max(seen_id, ev.event_id)
                    data_str = json.dumps(ev.model_dump(), sort_keys=True)
                    yield f"id: {ev.event_id}\nevent: {ev.event_type}\ndata: {data_str}\n\n"

                terminal_statuses = {
                    RunStatus.COMPLETED,
                    RunStatus.PARTIAL_BUDGET_EXHAUSTED,
                    RunStatus.REJECTED,
                    RunStatus.FAILED,
                }
                while True:
                    current_summary = db.get_run_summary(run_id)
                    if current_summary is None:
                        break
                    if current_summary.status in terminal_statuses and queue.empty():
                        break
                    if current_summary.status == RunStatus.AWAITING_APPROVAL and queue.empty():
                        yield ": awaiting_approval\n\n"
                        break

                    try:
                        live_ev = await asyncio.wait_for(queue.get(), timeout=1.0)
                        ev_id = int(live_ev.get("event_id", 0))
                        if ev_id > seen_id:
                            seen_id = ev_id
                            ev_type = str(live_ev.get("event_type", "message"))
                            data_str = json.dumps(live_ev, sort_keys=True)
                            yield f"id: {ev_id}\nevent: {ev_type}\ndata: {data_str}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                sse_hub.unsubscribe(run_id, queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/runs/{run_id}/decision", response_model=RunDetail, tags=["runs"])
    async def submit_human_decision(
        run_id: str,
        decision: HumanDecisionRequest,
        wait_for_completion: bool = Query(default=True),
    ) -> RunDetail:
        summary = db.get_run_summary(run_id)
        if summary is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error_code="RUN_NOT_FOUND",
                    message=f"Run '{run_id}' does not exist.",
                ).model_dump(),
            )
        if summary.status != RunStatus.AWAITING_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorResponse(
                    error_code="INVALID_RUN_STATE",
                    message=(
                        f"Run '{run_id}' is in status '{summary.status.value}', "
                        "not 'awaiting_approval'."
                    ),
                ).model_dump(),
            )

        if wait_for_completion:
            await orchestrator.resume_from_human_gate(
                run_id,
                action=decision.action,
                feedback=decision.feedback,
            )
        else:
            task = asyncio.create_task(
                orchestrator.resume_from_human_gate(
                    run_id,
                    action=decision.action,
                    feedback=decision.feedback,
                )
            )
            orchestrator._active_tasks[run_id] = task
            task.add_done_callback(lambda _: orchestrator._active_tasks.pop(run_id, None))

        detail = db.get_run_detail(run_id)
        assert detail is not None
        return detail

    @app.get("/runs/{run_id}/report.md", response_class=PlainTextResponse, tags=["runs"])
    async def get_run_report_markdown(run_id: str) -> PlainTextResponse:
        detail = db.get_run_detail(run_id)
        if detail is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error_code="RUN_NOT_FOUND",
                    message=f"Run '{run_id}' does not exist.",
                ).model_dump(),
            )
        if not detail.report_markdown:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorResponse(
                    error_code="REPORT_NOT_READY",
                    message=f"Report for run '{run_id}' is not yet finalized (status: {detail.status.value}).",
                ).model_dump(),
            )
        return PlainTextResponse(
            content=detail.report_markdown,
            media_type="text/markdown; charset=utf-8",
        )

    @app.get("/runs/{run_id}/ledger/verify", response_model=LedgerVerifyResponse, tags=["ledger"])
    async def verify_run_ledger_endpoint(run_id: str) -> LedgerVerifyResponse:
        summary = db.get_run_summary(run_id)
        if summary is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error_code="RUN_NOT_FOUND",
                    message=f"Run '{run_id}' does not exist.",
                ).model_dump(),
            )
        return db.verify_run_ledger(run_id)

    return app


app = create_app()
