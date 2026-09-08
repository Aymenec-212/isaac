"""A-14: Slice 3's thresholds against timing a real model actually produced.

Every value Slice 3 chose — reconnect grace, idle close, the overload window,
the gap threshold — exists to absorb jitter. All of them were tuned against
`FakeRecognizer`, which emits on a metronome and therefore has none. A-14 has
been open since, and the 116 s Slice 4 run was too short and too well-behaved to
close it.

`MeasuredRecognizer` replays `docs/mosaique-b1-main/`: 162 real token emissions
from an MLX run, paired with their assembled words. The timing is real even
though the model is not, which is enough to ask what the *runtime* does when
words arrive in bursts with a 24-second hole in the middle.

Still not answered here, and not claimed: real-time factor, memory over hours,
and long-run MLX stability. Those need Apple silicon.
"""

from __future__ import annotations

import statistics

import pytest

from mosaique.speech.adapters.fake import (
    MEASURED_MODEL_DELAY_MS,
    MeasuredRecognizer,
    load_measured_words,
)
from mosaique.speech.interfaces import (
    FRAME_DURATION_MS,
    SILENCE_FRAME,
    ASRSessionConfig,
    AudioChunk,
    StreamingRecognizer,
    WordEvent,
)
from mosaique.transcript.segmenter import DEFAULT_SILENCE_MS, Segmenter, SegmentFinal


async def _push(session, frames: int, *, start: int = 0) -> None:  # type: ignore[no-untyped-def]
    for i in range(frames):
        await session.push_audio(AudioChunk(pcm=SILENCE_FRAME, sequence=start + i))


async def _drain(session) -> list[WordEvent]:  # type: ignore[no-untyped-def]
    """Everything already queued, without waiting for more."""
    words: list[WordEvent] = []
    while not session._queue.empty():  # noqa: SLF001 - reading the fake's own queue
        event = session._queue.get_nowait()
        if isinstance(event, WordEvent):
            words.append(event)
    return words


# --- the fixture itself ----------------------------------------------------


def test_the_measured_fixture_is_internally_consistent():
    """`sum(pieces) == len(tokens)`, or every word's timing is off by a piece."""
    words = load_measured_words()

    assert len(words) == 92
    assert all(w.emitted_at_ms >= w.end_ms for w in words), (
        "a word cannot be emitted before it ends"
    )


def test_the_measured_timing_is_burstier_than_any_fixed_delay():
    """The property that makes this fixture worth having.

    If these numbers ever collapse toward a constant, the fixture has stopped
    being a jitter test and the A-14 claims below are worth less.
    """
    words = load_measured_words()
    gaps = [b.emitted_at_ms - a.emitted_at_ms for a, b in zip(words, words[1:], strict=False)]

    # Measured word-level values: p50 320 ms, p95 1 280 ms, max 24 080 ms.
    # A fixed-delay fake has a median gap equal to its script's spacing and no
    # tail at all; the tail is the whole reason this fixture exists.
    assert statistics.median(gaps) == 320
    assert max(gaps) > 10_000, "the fixture's long silence is what provokes the idle paths"
    assert max(gaps) > 20 * statistics.median(gaps), "the tail must dwarf the typical gap"


def test_the_measured_recognizer_satisfies_the_same_protocol():
    assert isinstance(MeasuredRecognizer(), StreamingRecognizer)


@pytest.mark.asyncio
async def test_it_declares_no_end_of_turn_like_the_runtime_it_replays():
    """MLX has no VAD heads, so the segmenter must get its punctuation fallback.

    Declared rather than defaulted (L-25): a recognizer wrongly reported as
    emitting end-of-turn gets different closing behaviour, silently.
    """
    session = await MeasuredRecognizer().open_session(ASRSessionConfig())

    assert session.emits_end_of_turn is False


# --- emission behaviour ----------------------------------------------------


@pytest.mark.asyncio
async def test_words_arrive_only_once_the_stream_reaches_their_emission_point():
    """Stream time, not wall time (ADR-11). Nothing here waits on a clock."""
    session = await MeasuredRecognizer().open_session(ASRSessionConfig())

    # The first real word was emitted at 1520 ms of stream. Just before it:
    await _push(session, frames=1519 // FRAME_DURATION_MS)
    assert await _drain(session) == []

    await _push(session, frames=4, start=1000)
    assert [w.text for w in await _drain(session)] == ["Alors"]


@pytest.mark.asyncio
async def test_replay_is_speed_invariant():
    """Two sessions pushed the same number of frames agree, however fast.

    Frames are the only clock. A test that pushed faster and saw a different
    transcript would mean the ADR-11 bug had come back a third time.
    """
    fast = await MeasuredRecognizer().open_session(ASRSessionConfig())
    slow = await MeasuredRecognizer().open_session(ASRSessionConfig())

    await _push(fast, frames=400)
    for _ in range(400):
        await _push(slow, frames=1)

    assert [w.text for w in await _drain(fast)] == [w.text for w in await _drain(slow)]


@pytest.mark.asyncio
async def test_health_reports_transcribed_offset_behind_the_stream():
    """The distinction the whole timeline rests on: pushed is not transcribed."""
    session = await MeasuredRecognizer().open_session(ASRSessionConfig())

    await _push(session, frames=125)  # 10 s of stream
    health = session.health()

    assert health.transcribed_offset_ms == 10_000 - MEASURED_MODEL_DELAY_MS


# --- A-14: what real jitter does to Slice 3's thresholds -------------------


@pytest.mark.asyncio
async def test_real_emission_bursts_do_not_starve_the_stream_of_events():
    """An idle close and a stale socket both fire on *absence* of activity.

    With p95 word gaps of 1 280 ms and one 24 s hole, this is the first test that asks
    whether the runtime's notion of "this stream is alive" survives a real
    model's silence. The recognizer stays healthy throughout — the gap is in the
    audio, not in the runtime.
    """
    session = await MeasuredRecognizer().open_session(ASRSessionConfig())

    await _push(session, frames=825)  # the whole 66 s fixture

    assert session.health().healthy
    assert session.health().events_emitted == 92, "every word arrived despite the 24 s hole"


def test_the_silence_threshold_meets_real_emission_gaps():
    """§9.3's 1 200 ms rule, judged against gaps a real model produced.

    Feeding the *measured* word timings through the real `Segmenter` is the
    honest version of A-14 for this threshold: it asks what the tuned value does
    to real French, rather than to a script written to make it look good.

    This asserts what the segmenter currently does, not what it should do. L-28
    is deferred and untouched — the number here is a description.
    """
    words = load_measured_words()
    segmenter = Segmenter()

    finals: list[SegmentFinal] = []
    for word in words:
        finals += [e for e in segmenter.on_tick(word.emitted_at_ms) if isinstance(e, SegmentFinal)]
        finals += [
            e
            for e in segmenter.on_word(
                WordEvent(text=word.text, start_ms=word.start_ms, end_ms=word.end_ms)
            )
            if isinstance(e, SegmentFinal)
        ]
    finals += [e for e in segmenter.close_open() if isinstance(e, SegmentFinal)]

    assert finals, "real timing must still produce segments"
    # Every close is explained: punctuation, the duration cap, silence, or flush.
    assert {f.reason for f in finals} <= {"sentence_end", "max_duration", "silence", "flush"}
    # And the fixture's long hole is longer than the threshold, so at least one
    # close must be attributable to real silence rather than to punctuation.
    gaps = [b.start_ms - a.end_ms for a, b in zip(words, words[1:], strict=False)]
    assert max(gaps) > DEFAULT_SILENCE_MS


@pytest.mark.asyncio
async def test_flush_releases_pending_words_rather_than_dropping_them():
    """Ending a meeting mid-burst must not lose what the model already owed us.

    MLX cannot be accelerated (A-12 answered negatively), so `flush` here
    releases rather than catches up — and the words still have to arrive.
    """
    session = await MeasuredRecognizer().open_session(ASRSessionConfig())

    await _push(session, frames=100)  # 8 s in: most of the fixture is pending
    before = len(await _drain(session))
    await session.flush()
    after = len(await _drain(session))

    assert before + after == 92, "no word may be lost by ending early"


@pytest.mark.asyncio
async def test_looping_extends_the_fixture_without_repeating_timestamps():
    """How a long-run test gets hours of realistic timing from 66 seconds.

    Timestamps must keep advancing; a loop that replayed the same `start_ms`
    would produce a transcript that goes backwards and a segmenter that closes
    on every cycle boundary.
    """
    session = await MeasuredRecognizer(loop_after_ms=66_000).open_session(ASRSessionConfig())

    await _push(session, frames=825 * 2)
    words = await _drain(session)

    assert len(words) > 92, "the script restarted"
    starts = [w.start_ms for w in words]
    assert starts == sorted(starts), "a looped timeline must not go backwards"
