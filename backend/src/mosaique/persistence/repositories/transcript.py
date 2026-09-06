"""Segments, participants, audio sessions, jobs, outputs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mosaique.domain.ids import new_id
from mosaique.persistence.models import (
    AudioSession,
    Job,
    MeetingOutputs,
    Participant,
    TranscriptSegment,
)
from mosaique.transcript.segmenter import WordTiming


class ParticipantRepository:
    def __init__(self, session: AsyncSession, organization_id: str) -> None:
        self._session = session
        self._organization_id = organization_id

    async def create(
        self, *, meeting_id: str, display_name: str, role: str, user_id: str | None = None
    ) -> Participant:
        participant = Participant(
            id=new_id(),
            meeting_id=meeting_id,
            organization_id=self._organization_id,
            user_id=user_id,
            display_name=display_name,
            role=role,
        )
        self._session.add(participant)
        await self._session.flush()
        return participant

    async def get(self, participant_id: str) -> Participant | None:
        stmt = select(Participant).where(
            Participant.id == participant_id,
            Participant.organization_id == self._organization_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_meeting(self, meeting_id: str) -> Sequence[Participant]:
        stmt = (
            select(Participant)
            .where(
                Participant.meeting_id == meeting_id,
                Participant.organization_id == self._organization_id,
            )
            .order_by(Participant.created_at)
        )
        return (await self._session.execute(stmt)).scalars().all()


class AudioSessionRepository:
    def __init__(self, session: AsyncSession, organization_id: str) -> None:
        self._session = session
        self._organization_id = organization_id

    async def create(
        self,
        *,
        audio_session_id: str,
        meeting_id: str,
        participant_id: str,
        epoch_ms: int,
        audio_object_key: str | None,
    ) -> AudioSession:
        """The id is supplied by the ingress, not minted here.

        The gateway assigns an `audio_session_id` when the socket opens and
        attributes every frame to it; segments reference the same id. Minting a
        second one here is how the foreign key breaks.
        """
        audio_session = AudioSession(
            id=audio_session_id,
            meeting_id=meeting_id,
            organization_id=self._organization_id,
            participant_id=participant_id,
            epoch_ms=epoch_ms,
            audio_object_key=audio_object_key,
        )
        self._session.add(audio_session)
        await self._session.flush()
        return audio_session

    async def finish(
        self, audio_session_id: str, *, frames_received: int, frames_dropped: int
    ) -> None:
        audio_session = await self._session.get(AudioSession, audio_session_id)
        if audio_session is None:
            return
        audio_session.frames_received = frames_received
        audio_session.frames_dropped = frames_dropped
        audio_session.ended_at = datetime.now(UTC)


class SegmentRepository:
    def __init__(self, session: AsyncSession, organization_id: str) -> None:
        self._session = session
        self._organization_id = organization_id

    async def add_final(
        self,
        *,
        meeting_id: str,
        participant_id: str,
        audio_session_id: str | None,
        sequence: int,
        start_ms: int,
        end_ms: int,
        text: str,
        words: list[WordTiming] | None,
        status: str = "final",
    ) -> str:
        """Insert one final segment. A retried write is a no-op (tech spec 10)."""
        segment_id = new_id()
        stmt = (
            pg_insert(TranscriptSegment)
            .values(
                id=segment_id,
                meeting_id=meeting_id,
                organization_id=self._organization_id,
                participant_id=participant_id,
                audio_session_id=audio_session_id,
                sequence=sequence,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                words=words,
                status=status,
            )
            .on_conflict_do_nothing(constraint="uq_segment_participant_sequence")
            .returning(TranscriptSegment.id)
        )
        result = (await self._session.execute(stmt)).scalar_one_or_none()
        if result is not None:
            return str(result)
        existing = await self._session.execute(
            select(TranscriptSegment.id).where(
                TranscriptSegment.participant_id == participant_id,
                TranscriptSegment.sequence == sequence,
            )
        )
        return str(existing.scalar_one())

    async def list_for_meeting(self, meeting_id: str) -> Sequence[TranscriptSegment]:
        """Display order: across participants by start time (tech spec 4)."""
        stmt = (
            select(TranscriptSegment)
            .where(
                TranscriptSegment.meeting_id == meeting_id,
                TranscriptSegment.organization_id == self._organization_id,
            )
            .order_by(TranscriptSegment.start_ms, TranscriptSegment.sequence)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def next_sequence(self, participant_id: str) -> int:
        """Restored from the database on restart, per tech spec 10."""
        stmt = select(func.max(TranscriptSegment.sequence)).where(
            TranscriptSegment.participant_id == participant_id
        )
        current = (await self._session.execute(stmt)).scalar_one_or_none()
        return 0 if current is None else int(current) + 1


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        kind: str,
        meeting_id: str,
        organization_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> bool:
        """Insert a job unless its idempotency key already exists.

        Returns True when this call created the row. `POST /end` twice must
        yield one job, and this is where that is enforced.
        """
        stmt = (
            pg_insert(Job)
            .values(
                id=new_id(),
                kind=kind,
                meeting_id=meeting_id,
                organization_id=organization_id,
                idempotency_key=idempotency_key,
                payload=payload,
                status="pending",
            )
            .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
            .returning(Job.id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def claim_one(self) -> Job | None:
        """Claim the next runnable job (tech spec 12.1)."""
        stmt = (
            select(Job)
            .where(Job.status == "pending", Job.next_run_at <= datetime.now(UTC))
            .order_by(Job.next_run_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = (await self._session.execute(stmt)).scalar_one_or_none()
        if job is not None:
            job.status = "running"
            job.attempts += 1
        return job

    async def count_for_meeting(self, meeting_id: str) -> int:
        stmt = select(func.count()).select_from(Job).where(Job.meeting_id == meeting_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def get_latest_for_meeting(self, meeting_id: str) -> Job | None:
        stmt = (
            select(Job).where(Job.meeting_id == meeting_id).order_by(Job.created_at.desc()).limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


class OutputsRepository:
    def __init__(self, session: AsyncSession, organization_id: str) -> None:
        self._session = session
        self._organization_id = organization_id

    async def store(
        self,
        *,
        meeting_id: str,
        transcript_version: int,
        processor_version: str,
        llm_model: str,
        outputs: dict[str, Any],
    ) -> None:
        """Written only on success (blueprint X-12): Job owns execution state."""
        stmt = (
            pg_insert(MeetingOutputs)
            .values(
                id=new_id(),
                meeting_id=meeting_id,
                organization_id=self._organization_id,
                transcript_version=transcript_version,
                processor_version=processor_version,
                llm_model=llm_model,
                summary=outputs["summary"],
                key_points=outputs.get("key_points"),
                decisions=outputs.get("decisions"),
                action_items=outputs.get("action_items"),
                open_questions=outputs.get("open_questions"),
            )
            .on_conflict_do_nothing(constraint="uq_outputs_meeting_version_processor")
        )
        await self._session.execute(stmt)

    async def get(self, meeting_id: str) -> MeetingOutputs | None:
        stmt = (
            select(MeetingOutputs)
            .where(
                MeetingOutputs.meeting_id == meeting_id,
                MeetingOutputs.organization_id == self._organization_id,
            )
            .order_by(MeetingOutputs.generated_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
