"""ParticipantSession: bounded queue and the ADR-11 timeline."""

from __future__ import annotations

import pytest

from mosaique.realtime.sessions.participant import (
    QUEUE_MAX_FRAMES,
    ParticipantSession,
    QueuedFrame,
)
from mosaique.speech.adapters.fake import FakeASRSession
from mosaique.speech.interfaces import FRAME_DURATION_MS, SILENCE_FRAME
from mosaique.transcript.segmenter import Segmenter

PCM = b"\x01\x02" * 1920


def make_session(epoch_ms: int = 0) -> ParticipantSession:
    return ParticipantSession(
        participant_id="p1",
        audio_session_id="a1",
        asr_session=FakeASRSession(script=[]),
        segmenter=Segmenter(),
        epoch_ms=epoch_ms,
    )


def test_stream_offset_advances_by_frame_duration_not_by_clock():
    session = make_session()
    assert session.stream_offset_ms == 0
    session.frames_pushed = 5
    assert session.stream_offset_ms == 5 * FRAME_DURATION_MS


def test_meeting_time_is_the_session_anchor_plus_stream_offset():
    session = make_session(epoch_ms=12_000)
    session.frames_pushed = 10
    assert session.meeting_time_ms == 12_000 + 800


def test_duplicate_sequence_is_dropped():
    session = make_session()
    session.accept(0, PCM, 0)
    session.accept(1, PCM, 0)
    session.accept(1, PCM, 0)  # duplicate
    assert session.frames_received == 2


def test_out_of_order_frame_is_dropped():
    session = make_session()
    session.accept(5, PCM, 0)
    session.accept(3, PCM, 0)
    assert session.frames_received == 1


def test_forward_gap_is_counted_as_missing():
    session = make_session()
    session.accept(0, PCM, 0)
    session.accept(4, PCM, 0)
    assert session.frames_missing == 3


def test_queue_is_bounded_and_overflow_is_counted():
    """Tech spec 8.4: queues are never unbounded."""
    session = make_session()
    accepted = [session.accept(i, PCM, 0) for i in range(QUEUE_MAX_FRAMES + 5)]
    assert accepted.count(False) == 5
    assert session.frames_dropped == 5
    assert session.queue_depth == QUEUE_MAX_FRAMES


async def test_push_pads_a_gap_with_silence_to_keep_the_timeline_aligned():
    """ADR-11: padding keeps stream offset, file offset and capture time equal."""
    session = make_session()
    padding = await session.push(QueuedFrame(seq=0, pcm=PCM, received_at_ms=0))
    assert padding == 0
    # Frames 1 and 2 were lost; frame 3 arrives.
    padding = await session.push(QueuedFrame(seq=3, pcm=PCM, received_at_ms=0))
    assert padding == 2
    assert session.frames_pushed == 4
    assert session.stream_offset_ms == 4 * FRAME_DURATION_MS


async def test_padding_pushes_real_silence_into_the_recognizer():
    asr = FakeASRSession(script=[])
    session = ParticipantSession(
        participant_id="p1",
        audio_session_id="a1",
        asr_session=asr,
        segmenter=Segmenter(),
        epoch_ms=0,
    )
    await session.push(QueuedFrame(seq=2, pcm=PCM, received_at_ms=0))
    assert asr.stream_offset_ms == 3 * FRAME_DURATION_MS
    assert len(SILENCE_FRAME) == 3840


async def test_an_enormous_gap_is_not_padded_into_minutes_of_silence():
    session = make_session()
    await session.push(QueuedFrame(seq=100_000, pcm=PCM, received_at_ms=0))
    assert session.frames_pushed == 1  # capped, not padded


@pytest.mark.parametrize("depth", [0, 24])
def test_below_the_lagging_threshold_the_stream_is_not_lagging(depth):
    session = make_session()
    for i in range(depth):
        session.accept(i, PCM, 0)
    assert session.lagging is False


def test_at_the_lagging_threshold_the_stream_reports_lagging():
    session = make_session()
    for i in range(25):
        session.accept(i, PCM, 0)
    assert session.lagging is True
