"""The eight tables of migration 1 (tech spec 4, as amended by blueprint A-5 and D-04).

Every tenant-owned row carries `organization_id` from the first migration even
though the prototype seeds one organization (ADR-08). Cross-tenant reads fail
closed in the repository layer, not here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mosaique.persistence.models.base import (
    Base,
    Json,
    created_at_col,
    ulid_pk,
    updated_at_col,
)

# Enum values are stored as short strings with CHECK constraints rather than
# native PG enums: adding a value later is a one-line constraint change instead
# of an ALTER TYPE migration.
MEETING_STATES = ("CREATED", "JOINABLE", "LIVE", "FINALIZING", "COMPLETED", "FAILED", "CANCELLED")
PARTICIPANT_ROLES = ("host", "guest")
SEGMENT_STATUSES = ("final", "gap")
JOB_STATUSES = ("pending", "running", "succeeded", "failed")
SOURCE_KINDS = ("direct",)  # blueprint D-04: one value today, the seam is what matters


def _in(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = ulid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("organization_id", "email", name="uq_users_org_email"),)

    id: Mapped[str] = ulid_pk()
    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint(_in("state", MEETING_STATES), name="state_valid"),
        CheckConstraint(_in("source_kind", SOURCE_KINDS), name="source_kind_valid"),
        Index("ix_meetings_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = ulid_pk()
    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    host_user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="CREATED")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="fr")

    # blueprint D-04: which ingress produced this meeting. One value for now.
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="direct")

    # NULL while live; set to 1 at COMPLETED (contradiction X-5).
    transcript_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asr_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    transcript_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    invite_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (
        CheckConstraint(_in("role", PARTICIPANT_ROLES), name="role_valid"),
        Index("ix_participants_meeting", "meeting_id"),
    )

    id: Mapped[str] = ulid_pk()
    meeting_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(8), nullable=False, default="guest")
    join_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class AudioSession(Base):
    __tablename__ = "audio_sessions"
    __table_args__ = (Index("ix_audio_sessions_participant", "participant_id"),)

    id: Mapped[str] = ulid_pk()
    meeting_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )
    # ADR-11 / D-02: server anchor for this session, relative to meeting.started_at.
    epoch_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=24000)
    frames_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = created_at_col()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint("participant_id", "sequence", name="uq_segment_participant_sequence"),
        CheckConstraint(_in("status", SEGMENT_STATUSES), name="status_valid"),
        Index("ix_segments_meeting_start", "meeting_id", "start_ms"),
    )

    id: Mapped[str] = ulid_pk()
    meeting_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )
    audio_session_id: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("audio_sessions.id", ondelete="SET NULL"), nullable=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # What the model said. Slice 6R item 7 never writes to this column again:
    # a human correction lands in `corrected_text` beside it, so `text` and
    # `words` stay exactly as the ASR produced them. That is what keeps L-28,
    # the 1.43% WER and every `[measure]` row falsifiable after the fact — Q9's
    # "additive only" constraint, enforced by where the data goes rather than by
    # a convention someone has to remember.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable: populated only when the adapter gives word timings for free (R-7).
    words: Mapped[Json | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="final")
    created_at: Mapped[datetime] = created_at_col()

    # --- corrections (Slice 6R item 7, Q9) --------------------------------
    # All three are NULL until somebody edits the segment. Reading code asks
    # for the *effective* value (`corrected_x or x`) and the raw one stays
    # available for anyone auditing what the model actually produced.
    corrected_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A misattributed segment is as wrong as a misheard word, and on one
    # microphone it is the likelier error (L-2).
    corrected_participant_id: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("participants.id", ondelete="SET NULL"), nullable=True
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Who to ask about an edit. Nullable because Slice 7 owns real identity
    # (Q4); until then this is the host user id from the token.
    corrected_by: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class MeetingOutputs(Base):
    """Derived intelligence. The row exists only on success (blueprint X-12, A-5)."""

    __tablename__ = "meeting_outputs"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "transcript_version",
            "processor_version",
            name="uq_outputs_meeting_version_processor",
        ),
    )

    id: Mapped[str] = ulid_pk()
    meeting_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transcript_version: Mapped[int] = mapped_column(Integer, nullable=False)
    processor_version: Mapped[str] = mapped_column(String(40), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[Json | None] = mapped_column(JSONB, nullable=True)
    decisions: Mapped[Json | None] = mapped_column(JSONB, nullable=True)
    action_items: Mapped[Json | None] = mapped_column(JSONB, nullable=True)
    open_questions: Mapped[Json | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[datetime] = created_at_col()


class Job(Base):
    """Execution state for async work. Job owns status; MeetingOutputs does not (X-12)."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        CheckConstraint(_in("status", JOB_STATUSES), name="status_valid"),
        Index("ix_jobs_claimable", "status", "next_run_at"),
    )

    id: Mapped[str] = ulid_pk()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # blueprint A-5: real FK, needed for cascade delete and querying.
    meeting_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[Json | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_run_at: Mapped[datetime] = created_at_col()
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()
