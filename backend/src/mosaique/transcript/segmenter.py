"""Words to interim/final segments (tech spec 9.3).

Because a streaming model emits final words continuously, "interim versus
final" is a *product* concept, not a model one: an open segment is interim, a
closed segment is final. This module owns that decision and nothing else.

Pure and synchronous by design. It takes time as an argument, never reads a
clock, performs no I/O, and holds no database or socket. That is what lets the
same code run in unit tests, in the replay harness, and in production, and it
is why segmentation thresholds can be tuned in Slice 4 against real French
audio without touching the runtime.

Invariant (blueprint X-14): within one segment, interim text only ever grows.
The chosen model does not retract emitted words, so `revision` is a monotone
counter, not a correction mechanism. The field stays because a future
recognizer may retract; the invariant is asserted in the tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TypedDict

from mosaique.speech.interfaces import EndOfTurnEvent, WordEvent


class WordTiming(TypedDict):
    """One word as stored in `TranscriptSegment.words` (R-7, nullable)."""

    w: str
    start_ms: int
    end_ms: int | None


# All three are [measure] in the specification. They are guesses until Slice 4
# tunes them against real French meeting audio using the replay harness.
DEFAULT_END_OF_TURN_THRESHOLD = 0.5
DEFAULT_SILENCE_MS = 700
DEFAULT_MAX_SEGMENT_MS = 15_000


@dataclass(frozen=True)
class SegmentDelta:
    """Interim text for an open segment. Broadcast, never persisted (ADR-05)."""

    sequence: int
    revision: int
    text: str
    start_ms: int


@dataclass(frozen=True)
class SegmentFinal:
    """A closed segment. Broadcast and persisted."""

    sequence: int
    revision: int
    text: str
    start_ms: int
    end_ms: int
    words: list[WordTiming]
    reason: str  # end_of_turn | silence | max_duration | flush


SegmenterEvent = SegmentDelta | SegmentFinal


@dataclass
class _OpenSegment:
    sequence: int
    start_ms: int
    revision: int = 0
    words: list[WordEvent] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def last_word_end_ms(self) -> int:
        last = self.words[-1]
        return last.end_ms if last.end_ms is not None else last.start_ms


class Segmenter:
    """Fold a word stream into segments for one participant."""

    def __init__(
        self,
        *,
        first_sequence: int = 0,
        end_of_turn_threshold: float = DEFAULT_END_OF_TURN_THRESHOLD,
        silence_ms: int = DEFAULT_SILENCE_MS,
        max_segment_ms: int = DEFAULT_MAX_SEGMENT_MS,
    ) -> None:
        self._next_sequence = first_sequence
        self._end_of_turn_threshold = end_of_turn_threshold
        self._silence_ms = silence_ms
        self._max_segment_ms = max_segment_ms
        self._open: _OpenSegment | None = None

    @property
    def has_open_segment(self) -> bool:
        return self._open is not None

    @property
    def next_sequence(self) -> int:
        return self._next_sequence

    def on_word(self, word: WordEvent) -> list[SegmenterEvent]:
        """Append a word, emitting a delta and possibly closing on the duration cap."""
        events: list[SegmenterEvent] = []
        if self._open is None:
            self._open = _OpenSegment(sequence=self._next_sequence, start_ms=word.start_ms)
            self._next_sequence += 1

        self._open.words.append(word)
        self._open.revision += 1
        events.append(
            SegmentDelta(
                sequence=self._open.sequence,
                revision=self._open.revision,
                text=self._open.text,
                start_ms=self._open.start_ms,
            )
        )

        # Hard cap: split at the last word boundary rather than mid-utterance.
        if self._open.last_word_end_ms - self._open.start_ms >= self._max_segment_ms:
            events.append(self._close("max_duration"))
        return events

    def on_end_of_turn(self, event: EndOfTurnEvent) -> list[SegmenterEvent]:
        if self._open is None or event.probability < self._end_of_turn_threshold:
            return []
        return [self._close("end_of_turn", at_ms=event.at_ms)]

    def on_tick(self, now_ms: int) -> list[SegmenterEvent]:
        """Close the open segment when the speaker has gone quiet long enough.

        `now_ms` is stream time derived from frames received (ADR-11), never a
        wall clock, so silence detection replays identically at any speed.
        """
        if self._open is None or not self._open.words:
            return []
        if now_ms - self._open.last_word_end_ms >= self._silence_ms:
            return [self._close("silence")]
        return []

    def close_open(self, reason: str = "flush") -> list[SegmenterEvent]:
        """Force closure at end of meeting or session teardown (tech spec 11)."""
        if self._open is None:
            return []
        return [self._close(reason)]

    def _close(self, reason: str, *, at_ms: int | None = None) -> SegmentFinal:
        assert self._open is not None
        segment = self._open
        self._open = None
        end_ms = at_ms if at_ms is not None else segment.last_word_end_ms
        return SegmentFinal(
            sequence=segment.sequence,
            revision=segment.revision + 1,
            text=segment.text,
            start_ms=segment.start_ms,
            end_ms=max(end_ms, segment.start_ms),
            words=[
                {"w": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms} for w in segment.words
            ],
            reason=reason,
        )


def shift(event: SegmenterEvent, offset_ms: int) -> SegmenterEvent:
    """Move an event from ASR-stream time onto the meeting timeline (ADR-11)."""
    if isinstance(event, SegmentDelta):
        return replace(event, start_ms=event.start_ms + offset_ms)
    return replace(
        event,
        start_ms=event.start_ms + offset_ms,
        end_ms=event.end_ms + offset_ms,
        words=[
            WordTiming(
                w=w["w"],
                start_ms=w["start_ms"] + offset_ms,
                end_ms=None if w["end_ms"] is None else w["end_ms"] + offset_ms,
            )
            for w in event.words
        ],
    )
