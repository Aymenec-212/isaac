"""Shared fixtures. Integration tests run against a real PostgreSQL (tech spec 14.2)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

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


@pytest.fixture
async def tenants(engine):  # type: ignore[no-untyped-def]
    """Two organizations, each with a host user. The basis of every tenancy test."""
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
async def client(engine) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    """ASGI client that skips lifespan, since the engine fixture already owns it."""
    from mosaique.app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def host_token_for(settings, tenant) -> str:  # type: ignore[no-untyped-def]
    from mosaique.app.auth.tokens import issue_host_token

    return issue_host_token(
        user_id=tenant["user_id"],
        organization_id=tenant["org_id"],
        secret=settings.token_secret,
        ttl_hours=1,
    )
