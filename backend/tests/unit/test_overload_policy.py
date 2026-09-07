"""The bounded queue and what happens when it fills (tech spec 8.4, 8.3).

The policy has one promise behind it: transcript text is never *silently*
lost. A frame the recognizer cannot keep up with leaves the ASR queue but not
the audio file, and the span it covers becomes a visible gap segment.
"""

from __future__ import annotations

import time

import pytest

from mosaique.realtime.sessions.participant import (
    QUEUE_MAX_FRAMES,
    ParticipantSession,
)
from mosaique.speech.interfaces import FRAME_PAYLOAD_BYTES, WordEvent
from mosaique.transcript.segmenter import Segmenter, SegmentFinal

PCM = b"\x00\x01" * (FRAME_PAYLOAD_BYTES // 2)


class _StubASR:
    """Enough of `ASRSession` for the queue bookkeeping under test."""

    async def push_audio(self, chunk: object) -> None: ...
    def events(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def flush(self) -> None: ...
    async def close(self) -> None: ...
    def health(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def make_session() -> ParticipantSession:
    return ParticipantSession(
        participant_id="p1",
        audio_session_id="a1",
        asr_session=_StubASR(),  # type: ignore[arg-type]
        segmenter=Segmenter(),
        epoch_ms=0,
    )


def fill(session: ParticipantSession, count: int, *, start: int = 0) -> None:
    for offset in range(count):
        session.accept(start + offset, PCM, 0)


def test_the_queue_accepts_up_to_its_ceiling():
    session = make_session()
    fill(session, QUEUE_MAX_FRAMES)
    assert session.queue_depth == QUEUE_MAX_FRAMES
    assert session.queue_full is True
    assert session.frames_skipped == 0


def test_a_full_queue_skips_the_frame_and_remembers_the_span():
    session = make_session()
    fill(session, QUEUE_MAX_FRAMES + 5)

    assert session.frames_skipped == 5
    # Nothing to report while the pressure is still on: the run is not over.
    assert session.take_skipped_span() is None


def test_the_skipped_span_is_reported_once_the_queue_drains():
    session = make_session()
    fill(session, QUEUE_MAX_FRAMES + 5)
    session._queue.get_nowait()  # the pump takes one, so the queue is no longer full

    span = session.take_skipped_span()
    assert span == (QUEUE_MAX_FRAMES, QUEUE_MAX_FRAMES + 4)
    # Reported once, so one run of overload yields one gap segment.
    assert session.take_skipped_span() is None


def test_lag_is_reported_in_milliseconds_of_queued_audio():
    session = make_session()
    fill(session, 25)
    assert session.lagging is True
    assert session.lag_ms == 25 * 80


def test_overload_duration_starts_at_the_first_skipped_frame():
    session = make_session()
    fill(session, QUEUE_MAX_FRAMES)
    assert session.overloaded_for_s() == 0.0

    session.accept(QUEUE_MAX_FRAMES, PCM, 0)
    time.sleep(0.02)
    assert session.overloaded_for_s() > 0.0


class TestGapSegments:
    def test_a_gap_closes_any_open_segment_first(self):
        segmenter = Segmenter()
        segmenter.on_word(WordEvent(text="Bonjour", start_ms=100, end_ms=300))

        events = segmenter.insert_gap(1000, 4000)
        finals = [e for e in events if isinstance(e, SegmentFinal)]
        assert len(finals) == 2, "the open segment and the gap"
        assert finals[0].text == "Bonjour"
        assert finals[0].reason == "gap_boundary"
        assert finals[1].reason == "gap"

    def test_a_gap_carries_the_span_it_covers_and_no_text(self):
        segmenter = Segmenter()
        [gap] = segmenter.insert_gap(1000, 4000)
        assert isinstance(gap, SegmentFinal)
        assert gap.text == ""
        assert (gap.start_ms, gap.end_ms) == (1000, 4000)
        assert gap.words == []

    def test_a_gap_takes_a_sequence_so_later_segments_do_not_reuse_it(self):
        segmenter = Segmenter()
        [gap] = segmenter.insert_gap(0, 1000)
        assert isinstance(gap, SegmentFinal)
        segmenter.on_word(WordEvent(text="Ensuite", start_ms=2000, end_ms=2200))
        [delta] = segmenter.on_word(WordEvent(text="donc", start_ms=2300, end_ms=2500))
        assert delta.sequence > gap.sequence

    @pytest.mark.parametrize("end_ms", [0, 500])
    def test_a_gap_never_ends_before_it_starts(self, end_ms: int):
        [gap] = Segmenter().insert_gap(1000, end_ms)
        assert isinstance(gap, SegmentFinal)
        assert gap.end_ms >= gap.start_ms
