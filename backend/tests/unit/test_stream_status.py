"""Queue depth to `stream.status` (tech spec 8.4, 7.2).

Driven directly rather than through a socket: the mapping is the thing worth
pinning down, and forcing a real queue to overflow through the gateway would
test the scheduler more than the policy.
"""

from __future__ import annotations

import pytest

from mosaique.realtime.ingress import MeetingRef
from mosaique.realtime.sessions.meeting import MeetingRuntime
from mosaique.realtime.sessions.participant import (
    OVERLOAD_FAILURE_S,
    QUEUE_LAGGING_FRAMES,
    QUEUE_MAX_FRAMES,
    ParticipantSession,
)
from mosaique.speech.interfaces import FRAME_PAYLOAD_BYTES
from mosaique.transcript.segmenter import Segmenter

PCM = b"\x00\x01" * (FRAME_PAYLOAD_BYTES // 2)


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, meeting_id: str, message: dict) -> None:
        self.published.append(message)

    async def send_to(self, participant_id: str, message: dict) -> None:
        self.published.append(message)


class _StubASR:
    async def push_audio(self, chunk: object) -> None: ...
    def events(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def flush(self) -> None: ...
    async def close(self) -> None: ...
    def health(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError


@pytest.fixture
def runtime_and_session():  # type: ignore[no-untyped-def]
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


def statuses(broadcaster: RecordingBroadcaster) -> list[tuple[str, int]]:
    return [
        (m["status"], m["lag_ms"]) for m in broadcaster.published if m["type"] == "stream.status"
    ]


async def test_an_empty_queue_reports_transcribing(runtime_and_session):
    runtime, session, broadcaster = runtime_and_session
    await runtime._update_stream_status(session)
    assert statuses(broadcaster) == [("transcribing", 0)]


async def test_a_backing_up_queue_reports_delayed_with_its_lag(runtime_and_session):
    runtime, session, broadcaster = runtime_and_session
    for seq in range(QUEUE_LAGGING_FRAMES):
        session.accept(seq, PCM, 0)

    await runtime._update_stream_status(session)
    assert statuses(broadcaster) == [("delayed", QUEUE_LAGGING_FRAMES * 80)]


async def test_a_muted_participant_reports_listening_not_a_fault(runtime_and_session):
    """R-1's whole point: mute must not look like a failure."""
    runtime, session, broadcaster = runtime_and_session
    session.paused = True
    await runtime._update_stream_status(session)
    assert statuses(broadcaster) == [("listening", 0)]


async def test_the_status_is_published_only_when_it_changes(runtime_and_session):
    """Depth moves every 80 ms; the status bar must not flicker with it."""
    runtime, session, broadcaster = runtime_and_session
    for _ in range(5):
        await runtime._update_stream_status(session)
    assert statuses(broadcaster) == [("transcribing", 0)]


async def test_sustained_overload_reports_unavailable(runtime_and_session, monkeypatch):
    """Tech spec 8.4: past the failure window, stop claiming to transcribe.

    Audio is still being recorded, which is exactly why the client has to be
    told plainly that the transcript is not keeping up.
    """
    runtime, session, broadcaster = runtime_and_session
    for seq in range(QUEUE_MAX_FRAMES + 1):
        session.accept(seq, PCM, 0)
    monkeypatch.setattr(type(session), "overloaded_for_s", lambda self: OVERLOAD_FAILURE_S + 1)

    await runtime._update_stream_status(session)
    assert statuses(broadcaster) == [("unavailable", 0)]
