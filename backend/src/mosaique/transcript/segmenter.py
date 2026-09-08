"""Words to interim/final segments (tech spec 9.3).

Because a streaming model emits final words continuously, "interim versus
final" is a *product* concept, not a model one: an open segment is interim, a
closed segment is final. This module owns that decision and nothing else.

Pure and synchronous by design. It takes time as an argument, never reads a
clock, performs no I/O, and holds no database or socket. That is what lets the
same code run in unit tests, in the replay harness, and in production, and it
is why segmentation thresholds can be tuned in Slice 4 against real French
audio without touching the runtime.

Closing rules, in the order they are checked (tech spec 9.3, as amended by
Spike B1): sentence-final punctuation, then the duration cap, on each word;
`EndOfTurnEvent` above threshold; silence in *stream* time; and `flush()`.
The punctuation rule is new in Slice 4 and the reasoning for it sits on
`DEFAULT_CLOSE_ON_SENTENCE_END` — in short, the runtime this project develops
against emits no end-of-turn event at all, and silence alone provably cannot
separate a sentence boundary from a mid-phrase pause for the one speaker
measured so far.

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


# Sentence-final punctuation the model emits. A word ending in one of these
# closes the segment (see `DEFAULT_CLOSE_ON_SENTENCE_END`).
SENTENCE_FINAL = (".", "!", "?", "\u2026")

# --- tech spec 9.3 `[measure]` values -------------------------------------
#
# Tuned in Slice 4 against `docs/spikes/B1-findings.md` — 64 s of one French
# speaker, 92 words, 91 inter-word gaps. Each value below says what evidence it
# rests on, because two of the three still rest on none.

DEFAULT_END_OF_TURN_THRESHOLD = 0.5
"""UNMEASURED, and deliberately not tuned.

The B1 VAD pass was skipped, and the `-mlx` weights carry no VAD heads at all,
so on that runtime no `EndOfTurnEvent` is ever produced and this threshold is
dead code. It is live on `moshi_server`, whose `Step` messages do carry a VAD
signal — which is where it will finally be measurable. Guessing a value from a
recognizer that cannot emit the event would be worse than leaving 0.5 standing.
"""

DEFAULT_SILENCE_MS = 1_200
"""MEASURED, thinly: raised from 700 ms on B1's word timings.

700 ms was wrong in a way one fixture was enough to show. In 64 s of ordinary
French it splits a phrase six times — `endroits | familiers`, `à | Casablanca`,
`crée | un` among them — because the largest *mid-phrase* gap that speaker
leaves is 1120 ms, while the smallest gap at a real sentence end is 880 ms.
The two distributions overlap, so **no silence threshold separates them**, and
that is the finding rather than the number: silence alone cannot carry
segmentation. 1200 ms clears the observed mid-phrase maximum with a little
margin and leaves the boundaries to the rule below.

One speaker, one recording. A second fixture can move it.
"""

DEFAULT_MAX_SEGMENT_MS = 15_000
"""UNMEASURED — the cap never fired. Longest natural segment observed: 12.7 s.

Retained unchanged. It is a safety net against a speaker who never pauses, and
B1 contained no such speaker, so nothing was learned about it.
"""

DEFAULT_CLOSE_ON_SENTENCE_END = True
"""MEASURED: the strongest boundary signal in the fixture, and the only one
available on MLX.

Kyutai emits punctuation, and in B1 every one of the three mid-transcript
sentence-final marks landed on a real boundary, with no false positive. Commas
do not count and were checked separately — the gaps after them run 0-640 ms,
squarely inside a phrase.

This is a rule the specification did not have, added because §9.3's primary
mechanism is absent on the development runtime: with no VAD heads, the MLX
segmenter would otherwise have only a silence timer that the paragraph above
shows cannot do the job alone.

The runtime enables it exactly where that is true — `ASRSession.emits_end_of_turn`
is False — and leaves it off where a semantic VAD exists. Running both at once
is untested: B1 measured punctuation against MLX output, and how it interacts
with `moshi_server`'s VAD is Spike B2's to find out, not this slice's to assume.

Configurable rather than hard-coded because of a risk one fixture cannot rule
out: a French abbreviation — `M.`, `Mme.`, `etc.` — ends in a period without
ending a sentence, and would split mid-phrase. None occurred in B1. See L-24.
"""


def ends_sentence(text: str) -> bool:
    """Does this word end a sentence?

    Trailing quotes and brackets are stripped first, so `dit."` counts. A word
    that is *only* punctuation does not: the model occasionally emits a bare
    mark, and closing on it would produce an empty segment.
    """
    stripped = text.rstrip("\"'\u00bb\u201d)]}")
    return bool(stripped) and stripped.endswith(SENTENCE_FINAL) and stripped not in SENTENCE_FINAL


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
        close_on_sentence_end: bool = DEFAULT_CLOSE_ON_SENTENCE_END,
    ) -> None:
        self._next_sequence = first_sequence
        self._end_of_turn_threshold = end_of_turn_threshold
        self._silence_ms = silence_ms
        self._max_segment_ms = max_segment_ms
        self._close_on_sentence_end = close_on_sentence_end
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

        # The model punctuates, and in B1 punctuation beat every timing signal
        # available (see DEFAULT_CLOSE_ON_SENTENCE_END). Checked before the
        # duration cap so a sentence that ends near the cap closes as a
        # sentence rather than as an overflow.
        if self._close_on_sentence_end and ends_sentence(word.text):
            events.append(self._close("sentence_end"))
            return events

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

    def insert_gap(self, start_ms: int, end_ms: int) -> list[SegmenterEvent]:
        """Mark a span of audio that was never transcribed (tech spec 8.3, 8.4).

        A gap is a first-class segment, not an omission. The invariant it
        protects is that final transcript text is never *silently* lost: audio
        skipped because the queue overflowed, or missing because frames never
        arrived, shows up as a visible marker at the right place on the
        timeline, and the raw audio for that span is still on disk.

        Any open segment is closed first, so a gap never lands inside a
        sentence the recognizer was still building.
        """
        events: list[SegmenterEvent] = []
        if self._open is not None:
            events.append(self._close("gap_boundary"))
        sequence = self._next_sequence
        self._next_sequence += 1
        events.append(
            SegmentFinal(
                sequence=sequence,
                revision=1,
                text="",
                start_ms=start_ms,
                end_ms=max(end_ms, start_ms),
                words=[],
                reason="gap",
            )
        )
        return events

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
