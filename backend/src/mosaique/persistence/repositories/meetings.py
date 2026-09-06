"""Meeting repository.

Tenancy rule (ADR-08, tech spec 4): every read and write is scoped by
`organization_id`, and the scope is a constructor argument rather than an
optional filter, so a caller cannot forget it. Cross-tenant reads return None
and therefore surface as MEETING_NOT_FOUND, never as a leak.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mosaique.domain.ids import new_id
from mosaique.domain.state import MeetingState
from mosaique.persistence.models import Meeting


class MeetingRepository:
    def __init__(self, session: AsyncSession, organization_id: str) -> None:
        self._session = session
        self._organization_id = organization_id

    async def create(
        self,
        *,
        host_user_id: str,
        title: str,
        state: MeetingState = MeetingState.CREATED,
        invite_token_hash: str | None = None,
    ) -> Meeting:
        meeting = Meeting(
            id=new_id(),
            organization_id=self._organization_id,
            host_user_id=host_user_id,
            title=title,
            state=str(state),
            language="fr",
            source_kind="direct",
            transcript_schema_version=1,
            invite_token_hash=invite_token_hash,
        )
        self._session.add(meeting)
        await self._session.flush()
        return meeting

    async def get(self, meeting_id: str) -> Meeting | None:
        """Fails closed: a meeting owned by another organization returns None."""
        stmt = select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.organization_id == self._organization_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(self, *, limit: int = 50, offset: int = 0) -> Sequence[Meeting]:
        stmt = (
            select(Meeting)
            .where(Meeting.organization_id == self._organization_id)
            .order_by(Meeting.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return (await self._session.execute(stmt)).scalars().all()
