"""Request and response schemas. These are the wire contract (tech spec 6)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorEnvelope(BaseModel):
    """Every failure response uses this shape (tech spec 6)."""

    error: ErrorBody


class ParticipantView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    role: str


class MeetingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    state: str
    language: str
    source_kind: str
    transcript_version: int | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class MeetingDetailView(MeetingView):
    participants: list[ParticipantView] = Field(default_factory=list)


class CreateMeetingRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class CreateMeetingResponse(BaseModel):
    meeting: MeetingView
    host_token: str
    invite_url: str


class MeetingListResponse(BaseModel):
    meetings: list[MeetingView]


class JoinRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    invite_token: str


class JoinResponse(BaseModel):
    participant: ParticipantView
    session_token: str
    ws_url: str
    meeting: MeetingView


class SegmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    participant_id: str
    sequence: int
    start_ms: int
    end_ms: int
    text: str
    status: str
    # Which stored recording this segment came from (FR-11). Nullable because a
    # gap segment (L-20) describes audio that was never received.
    audio_session_id: str | None = None


class AudioSessionView(BaseModel):
    """Where one participant's recording sits on the meeting timeline.

    The review page needs `epoch_ms` to turn a segment's meeting-relative
    `start_ms` into an offset inside the file:

        offset_ms = segment.start_ms - session.epoch_ms

    Sent alongside the segments rather than repeated on each one, because it is
    a property of the recording and there are a handful of recordings and
    hundreds of segments.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    participant_id: str
    epoch_ms: int


class TranscriptResponse(BaseModel):
    meeting_id: str
    transcript_version: int | None
    participants: list[ParticipantView]
    segments: list[SegmentView]
    audio_sessions: list[AudioSessionView] = []


class EvidenceItem(BaseModel):
    text: str
    evidence_segment_ids: list[str]


class ActionItemView(EvidenceItem):
    owner_participant_id: str | None = None
    owner_text: str | None = None
    due_text: str | None = None


class OutputsResponse(BaseModel):
    """202 while the job is pending; the body's `status` says which (X-12)."""

    status: str  # pending | running | failed | succeeded
    summary: str | None = None
    key_points: list[str] = Field(default_factory=list)
    decisions: list[EvidenceItem] = Field(default_factory=list)
    action_items: list[ActionItemView] = Field(default_factory=list)
    open_questions: list[EvidenceItem] = Field(default_factory=list)
    error_code: str | None = None


class EndMeetingResponse(BaseModel):
    meeting: MeetingView


class HealthResponse(BaseModel):
    status: str
    version: str


class DependencyView(BaseModel):
    """One dependency's state (tech spec 15, `/health/deps`)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    state: str
    detail: str
    # Carried in the response rather than left implicit, so a reader can see
    # *why* a failing LLM provider did not make the instance unready.
    gates_readiness: bool


class ReadinessResponse(BaseModel):
    status: str
    version: str
    summary: str
    dependencies: list[DependencyView]
