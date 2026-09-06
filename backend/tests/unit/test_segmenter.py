"""Segmenter behaviour (tech spec 9.3). Pure, no clock, no I/O."""

from __future__ import annotations

from mosaique.speech.interfaces import EndOfTurnEvent, WordEvent
from mosaique.transcript.segmenter import SegmentDelta, Segmenter, SegmentFinal, shift


def word(text: str, start_ms: int, end_ms: int | None = None) -> WordEvent:
    return WordEvent(text=text, start_ms=start_ms, end_ms=end_ms or start_ms + 200)


def test_each_word_emits_a_delta_with_growing_revision():
    seg = Segmenter()
    revisions = []
    for i, text in enumerate(["Bonjour,", "je", "pense"]):
        events = seg.on_word(word(text, 100 + i * 300))
        assert isinstance(events[0], SegmentDelta)
        revisions.append(events[0].revision)
    assert revisions == [1, 2, 3]


def test_interim_text_is_append_only_within_a_segment():
    """Blueprint X-14: the chosen model never retracts, so text only grows."""
    seg = Segmenter()
    texts = []
    for i, text in enumerate(["Le", "budget", "est", "validé."]):
        events = seg.on_word(word(text, i * 300))
        texts.append(next(e.text for e in events if isinstance(e, SegmentDelta)))
    for earlier, later in zip(texts, texts[1:], strict=False):
        assert later.startswith(earlier), f"{later!r} does not extend {earlier!r}"


def test_end_of_turn_above_threshold_closes_the_segment():
    seg = Segmenter()
    seg.on_word(word("Bonjour", 0))
    events = seg.on_end_of_turn(EndOfTurnEvent(at_ms=500, probability=0.9))
    assert len(events) == 1
    final = events[0]
    assert isinstance(final, SegmentFinal)
    assert final.reason == "end_of_turn"
    assert final.text == "Bonjour"
    assert not seg.has_open_segment


def test_end_of_turn_below_threshold_does_not_close():
    seg = Segmenter()
    seg.on_word(word("Bonjour", 0))
    assert seg.on_end_of_turn(EndOfTurnEvent(at_ms=500, probability=0.2)) == []
    assert seg.has_open_segment


def test_end_of_turn_with_no_open_segment_is_ignored():
    assert Segmenter().on_end_of_turn(EndOfTurnEvent(at_ms=10, probability=1.0)) == []


def test_silence_closes_the_segment_after_the_threshold():
    seg = Segmenter(silence_ms=700)
    seg.on_word(word("Bonjour", 0, end_ms=200))
    assert seg.on_tick(800) == []  # 600 ms of silence: not yet
    events = seg.on_tick(900)  # 700 ms: close
    assert isinstance(events[0], SegmentFinal)
    assert events[0].reason == "silence"


def test_duration_cap_closes_a_long_segment():
    seg = Segmenter(max_segment_ms=1000)
    seg.on_word(word("un", 0, end_ms=100))
    events = seg.on_word(word("deux", 1100, end_ms=1200))
    finals = [e for e in events if isinstance(e, SegmentFinal)]
    assert finals and finals[0].reason == "max_duration"


def test_flush_closes_whatever_is_open():
    seg = Segmenter()
    seg.on_word(word("Bonjour", 0))
    events = seg.close_open()
    assert isinstance(events[0], SegmentFinal)
    assert events[0].reason == "flush"
    assert seg.close_open() == []  # nothing left to close


def test_sequences_are_monotonic_and_resume_from_a_starting_point():
    seg = Segmenter(first_sequence=7)
    seg.on_word(word("un", 0))
    first = seg.close_open()[0]
    seg.on_word(word("deux", 1000))
    second = seg.close_open()[0]
    assert isinstance(first, SegmentFinal) and isinstance(second, SegmentFinal)
    assert (first.sequence, second.sequence) == (7, 8)


def test_final_carries_word_timings_for_fr11():
    seg = Segmenter()
    seg.on_word(word("Bonjour", 100, end_ms=400))
    final = seg.close_open()[0]
    assert isinstance(final, SegmentFinal)
    assert final.words == [{"w": "Bonjour", "start_ms": 100, "end_ms": 400}]


def test_shift_moves_events_onto_the_meeting_timeline():
    """ADR-11: ASR-stream time plus the session anchor equals meeting time."""
    seg = Segmenter()
    seg.on_word(word("Bonjour", 100, end_ms=400))
    final = seg.close_open()[0]
    moved = shift(final, 5_000)
    assert isinstance(moved, SegmentFinal)
    assert moved.start_ms == 5_100
    assert moved.end_ms == 5_400
    assert moved.words[0]["start_ms"] == 5_100


def test_shift_leaves_the_original_untouched():
    seg = Segmenter()
    seg.on_word(word("Bonjour", 100))
    final = seg.close_open()[0]
    shift(final, 1000)
    assert final.start_ms == 100
