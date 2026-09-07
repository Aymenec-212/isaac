"""The ingress seam (blueprint D-04).

Everything downstream of this boundary — meeting runtime, ASR adapter,
segmenter, persistence, intelligence — must not know where audio came from.
Today there is exactly one implementation, `BrowserWebSocketIngress`. A future
platform or SFU ingress replaces it without any of those layers changing.

The rule that earns the seam its keep is enforced by an architectural test:
**nothing downstream of this module imports WebSocket, FastAPI, or Starlette
types.** Deliberately absent: capability negotiation, platform identity
mapping, per-source consent modes. Those are hypothetical change points, and
the engineering skill is explicit about not abstracting them (skill 2.3).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MeetingRef:
    meeting_id: str
    organization_id: str


@dataclass(frozen=True)
class ParticipantJoined:
    participant_id: str
    display_name: str
    audio_session_id: str


@dataclass(frozen=True)
class ParticipantLeft:
    participant_id: str


@dataclass(frozen=True)
class IngressAudioFrame:
    """One canonical frame, already validated, attributed to a participant."""

    participant_id: str
    audio_session_id: str
    seq: int
    pcm: bytes


@dataclass(frozen=True)
class IngressError:
    participant_id: str | None
    code: str
    message: str


IngressEvent = ParticipantJoined | ParticipantLeft | IngressAudioFrame | IngressError


@dataclass(frozen=True)
class ResumeInfo:
    """What a `hello` needs to know about an existing stream (tech spec 7.4).

    The only thing the transport may ask the runtime, and it asks nothing about
    sockets: whether this participant's stream is still alive, and how far its
    frame sequence got.
    """

    resuming: bool
    last_sequence: int


@runtime_checkable
class MeetingIngress(Protocol):
    async def start(self, meeting: MeetingRef) -> None: ...

    def events(self) -> AsyncIterator[IngressEvent]: ...

    async def stop(self) -> None: ...


@runtime_checkable
class Broadcaster(Protocol):
    """The outbound counterpart of the ingress seam.

    The runtime produces transcript and state messages as plain dictionaries;
    how they reach a person is the transport's problem, not the runtime's.
    """

    async def publish(self, meeting_id: str, message: dict[str, object]) -> None: ...

    async def send_to(self, participant_id: str, message: dict[str, object]) -> None: ...
