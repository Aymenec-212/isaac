"""Meeting state machine (tech spec 5).

Pure functions over an enum. No I/O, no ORM, no framework types, so the whole
lifecycle is unit-testable without a database.
"""

from __future__ import annotations

from enum import StrEnum


class MeetingState(StrEnum):
    CREATED = "CREATED"
    JOINABLE = "JOINABLE"
    LIVE = "LIVE"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InvalidTransition(Exception):
    """Raised when a transition is not permitted from the current state."""

    def __init__(self, current: MeetingState, requested: str) -> None:
        super().__init__(f"cannot {requested} from {current}")
        self.current = current
        self.requested = requested


TERMINAL: frozenset[MeetingState] = frozenset(
    {MeetingState.COMPLETED, MeetingState.FAILED, MeetingState.CANCELLED}
)

ACCEPTS_AUDIO: frozenset[MeetingState] = frozenset({MeetingState.JOINABLE, MeetingState.LIVE})


def open_room(current: MeetingState) -> MeetingState:
    """CREATED -> JOINABLE. Idempotent once already joinable."""
    if current is MeetingState.CREATED:
        return MeetingState.JOINABLE
    if current is MeetingState.JOINABLE:
        return current
    raise InvalidTransition(current, "open_room")


def start(current: MeetingState) -> MeetingState:
    """JOINABLE -> LIVE, triggered by the host or the first accepted audio frame."""
    if current is MeetingState.JOINABLE:
        return MeetingState.LIVE
    if current is MeetingState.LIVE:
        return current
    raise InvalidTransition(current, "start")


def end(current: MeetingState) -> MeetingState:
    """LIVE -> FINALIZING. Idempotent from FINALIZING and COMPLETED (tech spec 5)."""
    if current is MeetingState.LIVE:
        return MeetingState.FINALIZING
    if current in (MeetingState.FINALIZING, MeetingState.COMPLETED):
        return current
    raise InvalidTransition(current, "end")


def complete(current: MeetingState) -> MeetingState:
    """FINALIZING -> COMPLETED once the drain reached a durable boundary."""
    if current is MeetingState.FINALIZING:
        return MeetingState.COMPLETED
    if current is MeetingState.COMPLETED:
        return current
    raise InvalidTransition(current, "complete")


def fail(current: MeetingState) -> MeetingState:
    """FINALIZING -> FAILED on unrecoverable persistence failure."""
    if current is MeetingState.FINALIZING:
        return MeetingState.FAILED
    if current is MeetingState.FAILED:
        return current
    raise InvalidTransition(current, "fail")


def cancel(current: MeetingState) -> MeetingState:
    """CREATED or JOINABLE -> CANCELLED. A live meeting must be ended, not cancelled."""
    if current in (MeetingState.CREATED, MeetingState.JOINABLE):
        return MeetingState.CANCELLED
    if current is MeetingState.CANCELLED:
        return current
    raise InvalidTransition(current, "cancel")


def accepts_audio(current: MeetingState) -> bool:
    """Audio frames are rejected with MEETING_NOT_LIVE outside these states."""
    return current in ACCEPTS_AUDIO
