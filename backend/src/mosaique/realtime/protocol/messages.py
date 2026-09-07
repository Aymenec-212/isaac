"""WebSocket control and transcript messages (tech spec 7.1, 7.2).

The protocol is versioned (`v: 1`) so the transport can change without the
runtime changing. Messages defined here but unused in Slice 1 are marked; they
exist now because the wire format is versioned and adding fields later is
harder than carrying them (blueprint X-13).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1


class Hello(BaseModel):
    """First message on every socket. No audio is accepted before hello.ok."""

    v: Literal[1] = 1
    type: Literal["hello"]
    session_token: str
    # Carried from Slice 1, consumed by reconnect in Slice 3 (blueprint X-13).
    last_ack_sequence: int | None = None
    client: dict[str, object] = Field(default_factory=dict)


class Ping(BaseModel):
    v: Literal[1] = 1
    type: Literal["ping"]
    t: int


class AudioPause(BaseModel):
    """Accepted and ignored in Slice 1; behaviour lands in Slice 3 (R-1)."""

    v: Literal[1] = 1
    type: Literal["audio.pause", "audio.resume"]


ClientMessage = Hello | Ping | AudioPause


class HelloOk(BaseModel):
    type: Literal["hello.ok"] = "hello.ok"
    participant_id: str
    display_name: str
    meeting_state: str
    meeting_started_at: int | None
    resume: bool = False


class TranscriptDelta(BaseModel):
    type: Literal["transcript.delta"] = "transcript.delta"
    participant_id: str
    sequence: int
    revision: int
    status: Literal["interim"] = "interim"
    text: str
    start_ms: int


class TranscriptSegmentFinal(BaseModel):
    type: Literal["transcript.segment.final"] = "transcript.segment.final"
    participant_id: str
    sequence: int
    revision: int
    status: Literal["final"] = "final"
    segment_id: str
    text: str
    start_ms: int
    end_ms: int


class ParticipantEvent(BaseModel):
    """Roster changes. Derived from ingress events, never from socket counts."""

    type: Literal["participant.joined", "participant.left"]
    participant_id: str
    display_name: str


class ParticipantSpeaking(BaseModel):
    """Who is talking right now.

    Derived from the segmenter — a participant is speaking while they have an
    open segment — so it is a statement about recognized speech rather than
    about microphone level, and it costs no extra signal on the wire.
    """

    type: Literal["participant.speaking"] = "participant.speaking"
    participant_id: str
    speaking: bool


class MeetingStateMessage(BaseModel):
    type: Literal["meeting.state"] = "meeting.state"
    state: str


class OutputsReady(BaseModel):
    type: Literal["meeting.outputs.ready"] = "meeting.outputs.ready"


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    fatal: bool = False


class Pong(BaseModel):
    type: Literal["pong"] = "pong"
    t: int
