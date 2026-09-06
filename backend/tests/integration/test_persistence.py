"""Durability and repository-level tenancy."""

from __future__ import annotations

import pytest

from mosaique.persistence.engine import session_scope
from mosaique.persistence.repositories.meetings import MeetingRepository

pytestmark = pytest.mark.integration


async def test_meeting_survives_a_new_session(tenants):
    """Slice 0 durability: written in one session, still there in the next."""
    alpha = tenants["alpha"]
    async with session_scope() as s:
        repo = MeetingRepository(s, alpha["org_id"])
        meeting = await repo.create(host_user_id=alpha["user_id"], title="Persistant")
        meeting_id = meeting.id

    async with session_scope() as s2:
        again = await MeetingRepository(s2, alpha["org_id"]).get(meeting_id)
        assert again is not None
        assert again.title == "Persistant"


async def test_repository_scope_blocks_cross_tenant_get(tenants):
    alpha, beta = tenants["alpha"], tenants["beta"]
    async with session_scope() as s:
        meeting = await MeetingRepository(s, alpha["org_id"]).create(
            host_user_id=alpha["user_id"], title="Alpha"
        )
        meeting_id = meeting.id

    async with session_scope() as s2:
        assert await MeetingRepository(s2, beta["org_id"]).get(meeting_id) is None


async def test_every_tenant_owned_table_has_organization_id():
    """ADR-08 is structural, so assert it against the real schema."""
    from mosaique.persistence.models import Base

    expected = {
        "meetings",
        "participants",
        "audio_sessions",
        "transcript_segments",
        "meeting_outputs",
        "jobs",
        "users",
    }
    for name in expected:
        table = Base.metadata.tables[name]
        assert "organization_id" in table.columns, f"{name} is missing organization_id"


async def test_all_eight_tables_exist_in_migration_one():
    from mosaique.persistence.models import Base

    assert set(Base.metadata.tables) == {
        "organizations",
        "users",
        "meetings",
        "participants",
        "audio_sessions",
        "transcript_segments",
        "meeting_outputs",
        "jobs",
    }
