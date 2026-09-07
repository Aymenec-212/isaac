"""What happens when the database goes away mid-meeting (failure matrix row 11).

The rule is that the meeting keeps working. Audio keeps being recorded, the
transcript keeps reaching the browser, and the segments queue up until the
database comes back — up to a stated limit, past which the client is told
plainly rather than left believing the transcript is safe.
"""

from __future__ import annotations

import pytest

from mosaique.realtime.ingress import MeetingRef
from mosaique.realtime.sessions import meeting as meeting_module
from mosaique.realtime.sessions.meeting import MeetingRuntime, _PendingSegment
from mosaique.realtime.sessions.participant import ParticipantSession
from mosaique.transcript.segmenter import Segmenter
from tests.unit.test_stream_status import RecordingBroadcaster, _StubASR


def make_runtime():  # type: ignore[no-untyped-def]
    broadcaster = RecordingBroadcaster()
    runtime = MeetingRuntime(
        meeting=MeetingRef(meeting_id="m1", organization_id="o1"),
        ingress=None,  # type: ignore[arg-type]
        broadcaster=broadcaster,  # type: ignore[arg-type]
        recognizer=None,  # type: ignore[arg-type]
        audio_store=None,  # type: ignore[arg-type]
        started_at_ms=0,
    )
    session = ParticipantSession(
        participant_id="p1",
        audio_session_id="a1",
        asr_session=_StubASR(),  # type: ignore[arg-type]
        segmenter=Segmenter(),
        epoch_ms=0,
    )
    return runtime, session, broadcaster


def segment(n: int) -> _PendingSegment:
    return _PendingSegment(
        segment_id=f"seg-{n}",
        participant_id="p1",
        audio_session_id="a1",
        sequence=n,
        start_ms=n * 1000,
        end_ms=n * 1000 + 900,
        text=f"phrase {n}",
        words=[],
        status="final",
    )


class _Unavailable:
    """A `session_scope` that always fails, like a database that is down."""

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        raise ConnectionError("database is unavailable")

    async def __aexit__(self, *exc: object) -> None:  # pragma: no cover
        return None


@pytest.fixture
def database_down(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(meeting_module, "session_scope", lambda: _Unavailable())


async def test_segments_are_held_rather_than_lost(database_down):
    runtime, session, _ = make_runtime()
    for n in range(5):
        await runtime._persist(session, segment(n))
    assert len(runtime._pending) == 5


async def test_the_buffer_stops_growing_at_the_stated_limit(database_down, monkeypatch):
    monkeypatch.setattr(meeting_module, "PERSISTENCE_BUFFER_MAX", 10)
    runtime, session, broadcaster = make_runtime()

    for n in range(25):
        await runtime._persist(session, segment(n))

    assert len(runtime._pending) == 10, "the buffer grew past its ceiling"
    statuses = [m for m in broadcaster.published if m["type"] == "stream.status"]
    assert statuses and statuses[-1]["status"] == "unavailable", (
        "the client was never told the transcript had stopped being written"
    )


async def test_recovery_writes_everything_that_was_held(monkeypatch):
    """When the database returns, the backlog goes with the next segment."""
    runtime, session, _ = make_runtime()
    written: list[str] = []

    class _Recorder:
        def __init__(self, *args: object, **kwargs: object) -> None: ...

        async def add_final(self, **kwargs: object) -> str:
            written.append(str(kwargs["segment_id"]))
            return str(kwargs["segment_id"])

    class _Scope:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return object()

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(meeting_module, "session_scope", lambda: _Unavailable())
    for n in range(3):
        await runtime._persist(session, segment(n))
    assert len(runtime._pending) == 3

    monkeypatch.setattr(meeting_module, "session_scope", lambda: _Scope())
    monkeypatch.setattr(meeting_module, "SegmentRepository", _Recorder)
    await runtime._persist(session, segment(3))

    assert written == ["seg-0", "seg-1", "seg-2", "seg-3"], (
        "the backlog was not written in order when the database came back"
    )
    assert runtime._pending == []
