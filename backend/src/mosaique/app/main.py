"""FastAPI application factory."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mosaique import __version__
from mosaique.app.api import health, meetings
from mosaique.config.settings import Settings, get_settings
from mosaique.domain.errors import ErrorCode, MosaiqueError
from mosaique.intelligence.provider import FakeLLMProvider
from mosaique.jobs import MeetingIntelligenceProcessor
from mosaique.observability.logging import configure_logging, get_logger, request_id_var
from mosaique.persistence.engine import dispose_engine, init_engine
from mosaique.realtime.gateway import endpoint as ws_endpoint
from mosaique.realtime.runtime_state import init_registry, shutdown_registry
from mosaique.speech.adapters.fake import FakeRecognizer

log = get_logger(__name__)


async def recover_finalizing_meetings() -> None:
    """Tech spec 5 and 11: a meeting stuck in FINALIZING is re-driven on startup.

    The live ASR sessions are gone, so there is nothing left to drain; the
    already-persisted final segments stand, the meeting completes, and the
    intelligence job is enqueued. Steps 4-6 are idempotent, which is what makes
    this safe to run on every boot.
    """
    from sqlalchemy import select

    from mosaique.domain.state import MeetingState
    from mosaique.jobs import JOB_KIND, PROCESSOR_VERSION
    from mosaique.persistence.engine import session_scope
    from mosaique.persistence.models import Meeting
    from mosaique.persistence.repositories.transcript import JobRepository

    async with session_scope() as db:
        stmt = select(Meeting).where(Meeting.state == str(MeetingState.FINALIZING))
        stranded = (await db.execute(stmt)).scalars().all()
        for meeting in stranded:
            meeting.state = str(MeetingState.COMPLETED)
            meeting.transcript_version = 1
            meeting.ended_at = datetime.now(UTC)
            await JobRepository(db).enqueue(
                kind=JOB_KIND,
                meeting_id=meeting.id,
                organization_id=meeting.organization_id,
                idempotency_key=f"{meeting.id}:1:{PROCESSOR_VERSION}",
                payload={"transcript_version": 1, "processor_version": PROCESSOR_VERSION},
            )
            log.info("finalizing_meeting_recovered", meeting_id=meeting.id)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.environment != "local")
    init_engine(settings)

    # Slice 1 runs on fakes end to end. Slice 4 swaps in the Kyutai adapter and
    # Slice 5 a real provider; nothing else in the app changes.
    init_registry(recognizer=FakeRecognizer(), audio_root=settings.audio_root)
    processor = MeetingIntelligenceProcessor(FakeLLMProvider())
    processor.start()

    await recover_finalizing_meetings()
    log.info("app_started", environment=settings.environment, version=__version__)
    yield
    await processor.stop()
    await shutdown_registry()
    await dispose_engine()
    log.info("app_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Mosaique",
        version=__version__,
        summary="Realtime meeting intelligence, French-first",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def correlation_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(MosaiqueError)
    async def handle_domain_error(request: Request, exc: MosaiqueError) -> JSONResponse:
        """Map internal failures onto stable public codes (tech spec 13.4)."""
        request_id = request_id_var.get() or ""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": str(exc.code),
                    "message": exc.message,
                    "request_id": request_id,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Never leak a stack trace or a vendor exception to a client."""
        request_id = request_id_var.get() or ""
        log.error("unhandled_exception", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": str(ErrorCode.INTERNAL_ERROR),
                    "message": "Internal error",
                    "request_id": request_id,
                }
            },
        )

    app.include_router(health.router)
    app.include_router(meetings.router)
    app.include_router(ws_endpoint.router)
    return app
