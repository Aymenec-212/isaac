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
    """One segment as the review page should show it.

    **`text` and `participant_id` are the *effective* values** — the correction
    when one exists, the model's output otherwise. That choice is what keeps
    Slice 6R item 7 from breaking the two features built before it: search
    matches what a reader can see, and highlight offsets index into the string
    actually rendered. A client that had to decide which field to display would
    be a client that gets it wrong somewhere.

    The raw values are not lost, they are just not the default: `original_text`
    and `original_participant_id` are populated **only** when a correction
    exists, so an auditor can always recover what the ASR said (Q9, additive).
    """

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
    # Null unless this segment was corrected. Their presence *is* the "edited"
    # flag; a separate boolean could disagree with them.
    original_text: str | None = None
    original_participant_id: str | None = None
    corrected_at: datetime | None = None


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


class SegmentMatchView(BaseModel):
    """Where a search query matched inside one segment (FR-10).

    Offsets come from the server rather than being recomputed in the browser,
    so a highlight cannot disagree with what was actually matched — the two
    would otherwise need identical accent-folding in two languages.
    """

    segment_id: str
    # Half-open [start, end) into the segment's original text.
    spans: list[tuple[int, int]]


class TranscriptResponse(BaseModel):
    meeting_id: str
    transcript_version: int | None
    participants: list[ParticipantView]
    segments: list[SegmentView]
    audio_sessions: list[AudioSessionView] = []
    # Echoed so a client can tell a filtered transcript from a whole one, and
    # so a stale response cannot be mistaken for a result for the current query.
    query: str | None = None
    # How many segments the meeting has in total, before filtering. Lets the UI
    # say "3 of 30" rather than leaving someone unsure whether the rest is gone.
    total_segments: int = 0
    matches: list[SegmentMatchView] = []


class EvidenceItem(BaseModel):
    text: str
    evidence_segment_ids: list[str]


class ActionItemView(EvidenceItem):
    owner_participant_id: str | None = None
    owner_text: str | None = None
    due_text: str | None = None


class CorrectSegmentRequest(BaseModel):
    """A human edit to one segment (Slice 6R item 7, Q9).

    Both fields optional and at least one required: the two errors are
    independent. A misheard word needs `text`; a segment attributed to the wrong
    person needs `participant_id`, and on a single shared microphone that is the
    likelier mistake (L-2).

    Timestamps are deliberately **not** editable. They are derived from frame
    counts (ADR-11) and are what FR-11's audio seeking arithmetic rests on;
    letting someone type a number there would desynchronise a citation from its
    recording. Named here so the omission reads as a decision rather than an
    oversight.
    """

    text: str | None = Field(default=None, min_length=1, max_length=4000)
    participant_id: str | None = None


class OutputsResponse(BaseModel):
    """202 while the job is pending; the body's `status` says which (X-12)."""

    status: str  # pending | running | failed | succeeded
    # Which transcript these outputs were derived from, and which one the
    # meeting is on now. When they differ the transcript has been corrected
    # since — the review page says "à revoir" and offers to regenerate rather
    # than silently showing a summary of text nobody can see any more.
    generated_from_transcript_version: int | None = None
    current_transcript_version: int | None = None
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
