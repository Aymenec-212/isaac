"""Shared fixtures. Integration tests run against a real PostgreSQL (tech spec 14.2)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

TEST_DSN = os.environ.get(
    "MOSAIQUE_TEST_DATABASE_URL",
    "postgresql+asyncpg://mosaique:mosaique@localhost:5432/mosaique_test",
)
os.environ.setdefault("MOSAIQUE_DATABASE_URL", TEST_DSN)
os.environ.setdefault("MOSAIQUE_TOKEN_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("MOSAIQUE_ENVIRONMENT", "ci")


@pytest.fixture(scope="session")
def settings():  # type: ignore[no-untyped-def]
    from mosaique.config.settings import get_settings

    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
async def engine(settings):  # type: ignore[no-untyped-def]
    from mosaique.persistence.engine import dispose_engine, init_engine
    from mosaique.persistence.models import Base

    eng = init_engine(settings)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await dispose_engine()


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    from mosaique.persistence.engine import get_sessionmaker

    async with get_sessionmaker()() as s:
        yield s
        await s.rollback()


TABLES = (
    "jobs, meeting_outputs, transcript_segments, audio_sessions, "
    "participants, meetings, users, organizations"
)


@pytest.fixture
async def tenants(engine):  # type: ignore[no-untyped-def]
    """Two organizations, each with a host user. The basis of every tenancy test.

    Truncates first. Without this, rows survive between tests in the same
    session and the job processor happily claims a *previous* test's pending
    job — which is exactly the kind of cross-test coupling that makes a suite
    lie about what it proves.
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))

    from mosaique.domain.ids import new_id
    from mosaique.persistence.engine import session_scope
    from mosaique.persistence.models import Organization, User

    made = {}
    async with session_scope() as s:
        for label in ("alpha", "beta"):
            org = Organization(id=new_id(), name=f"Org {label}")
            s.add(org)
            await s.flush()
            user = User(
                id=new_id(),
                organization_id=org.id,
                email=f"host@{label}.test",
                display_name=f"Host {label}",
            )
            s.add(user)
            await s.flush()
            made[label] = {"org_id": org.id, "user_id": user.id}
    return made


@pytest.fixture
async def runtime(engine):  # type: ignore[no-untyped-def]
    """Slice 1 wiring: fake recognizer, in-memory audio, no job loop running.

    The processor is driven explicitly with `run_once()` in tests rather than
    left polling, so job assertions are deterministic.
    """
    from mosaique.realtime.runtime_state import init_registry, shutdown_registry
    from mosaique.speech.adapters.fake import FakeRecognizer
    from mosaique.speech.audio import NullAudioStore

    recognizer = FakeRecognizer()
    init_registry(
        recognizer=recognizer,
        audio_root=Path("/tmp/mosaique-tests"),
        audio_store=NullAudioStore(),
    )
    yield recognizer
    await shutdown_registry()


@pytest.fixture
async def client(engine, runtime) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    """ASGI client that skips lifespan, since the engine fixture already owns it."""
    from mosaique.app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class ASGIWebSocket:
    """Drives an ASGI websocket in the *current* event loop.

    Starlette's TestClient runs the app on its own loop in another thread,
    which asyncpg refuses to share. Speaking ASGI directly keeps the socket,
    the app, and the database engine on one loop, so these tests exercise the
    real gateway rather than a mock of it.
    """

    def __init__(self, app, path: str) -> None:  # type: ignore[no-untyped-def]
        self._app = app
        self._path = path
        self._to_app: asyncio.Queue = asyncio.Queue()
        self._from_app: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> ASGIWebSocket:
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": self._path,
            "raw_path": self._path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"test")],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
            "subprotocols": [],
            "state": {},
        }
        self._task = asyncio.create_task(self._app(scope, self._to_app.get, self._from_app.put))
        await self._to_app.put({"type": "websocket.connect"})
        first = await asyncio.wait_for(self._from_app.get(), timeout=5)
        if first["type"] != "websocket.accept":
            raise AssertionError(f"socket not accepted: {first}")
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except TimeoutError:
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

    async def send_json(self, payload: dict) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": json.dumps(payload)})

    async def send_bytes(self, payload: bytes) -> None:
        await self._to_app.put({"type": "websocket.receive", "bytes": payload})

    async def receive_json(self, timeout: float = 5.0) -> dict:
        while True:
            message = await asyncio.wait_for(self._from_app.get(), timeout=timeout)
            if message["type"] == "websocket.close":
                raise ConnectionError(f"closed with code {message.get('code')}")
            if "text" in message and message["text"] is not None:
                return json.loads(message["text"])

    def drain(self) -> list[dict]:
        """Everything the server has queued so far, without waiting."""
        out: list[dict] = []
        while True:
            try:
                message = self._from_app.get_nowait()
            except asyncio.QueueEmpty:
                return out
            if message.get("text"):
                out.append(json.loads(message["text"]))


class WsClient:
    def __init__(self, http: AsyncClient, app) -> None:  # type: ignore[no-untyped-def]
        self.http = http
        self._app = app

    def websocket_connect(self, path: str) -> ASGIWebSocket:
        return ASGIWebSocket(self._app, path)


@pytest.fixture
async def ws_client(engine, runtime):  # type: ignore[no-untyped-def]
    from mosaique.app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield WsClient(http=http, app=app)


def host_token_for(settings, tenant) -> str:  # type: ignore[no-untyped-def]
    from mosaique.app.auth.tokens import issue_host_token

    return issue_host_token(
        user_id=tenant["user_id"],
        organization_id=tenant["org_id"],
        secret=settings.token_secret,
        ttl_hours=1,
    )
