"""A fake that replays *measured* emission timing, not a fixed script (A-14).

`FakeRecognizer` emits a scripted line at a constant delay. That is the right
tool for testing the product path, and the wrong one for testing the thresholds
Slice 3 chose — reconnect grace, idle close, the overload window — because those
values exist precisely to absorb the jitter a real model produces, and a fixed
delay has none. A-14 has said so since Slice 3: those thresholds have never met
a recognizer whose timing was not a metronome.

This replays the real thing. `docs/mosaique-b1-main/b1-tokens.jsonl` is the
token-by-token log of an actual MLX run on Apple silicon: 162 tokens, each with
the stream position at which the model emitted it. Pairing those with the 92
assembled words in `b1-report.json` gives, for every word, **the stream offset at
which a real model actually produced it**.

What that buys, measured from the same data:

| per word | fake | measured |
|---|---|---|
| gap since the previous word | fixed | p50 320 ms, p95 1 280 ms, **max 24 s** |
| lag behind the word's own start | fixed 500 ms | p50 500, p95 740, max 900 ms |

(Word-level, because words are what this emits. The underlying *token* stream is
burstier still — p50 one 80 ms step — but the runtime never sees tokens.)

The 24-second maximum is the fixture's long silence, and it is exactly the shape
that provokes an idle close or a stale-socket timeout. No fixed-delay fake can
produce it.

**Replayed in stream time, never wall time** (ADR-11). Emission is keyed to
frames pushed, so a test at 60x sees the same transcript as a test at 1x — the
property the whole harness depends on, and the trap this codebase has fallen
into twice.

This is still a fake: it imports no model, loads no weights, and runs on Linux.
It does not make MLX numbers measurable — real-time factor, memory over hours
and long-run stability still need Apple silicon. It makes the *runtime's
reaction* to real timing testable, which is a different and cheaper question.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from mosaique.speech.interfaces import (
    FRAME_DURATION_MS,
    ASREvent,
    ASRHealth,
    AsrIdentity,
    ASRSessionConfig,
    AudioChunk,
    RecognizerReadiness,
    WordEvent,
)

# Where the measured run lives. Committed, so this needs no hardware.
# fake/ -> adapters/ -> speech/ -> mosaique/ -> src/ -> backend/ -> repo root.
B1_DIR = Path(__file__).resolve().parents[6] / "docs" / "mosaique-b1-main"
B1_REPORT = B1_DIR / "b1-report.json"
B1_TOKENS = B1_DIR / "b1-tokens.jsonl"

# What B1 read out of the build itself, not a guess (`audio_delay_seconds`).
MEASURED_MODEL_DELAY_MS = 500

# The identity is a fake's, deliberately. A transcript this produced must never
# be mistaken for one the model produced, even though the *timing* is real.
MEASURED_IDENTITY = AsrIdentity(
    model_id="fake/b1-replay", runtime="fake", quantization="measured-timing"
)


@dataclass(frozen=True)
class MeasuredWord:
    """One word, and the stream offset at which a real model emitted it."""

    text: str
    start_ms: int
    end_ms: int
    # Always >= start_ms. The difference is the model's emission lag, and it is
    # the whole point of this fixture.
    emitted_at_ms: int


def load_measured_words(report: Path = B1_REPORT, tokens: Path = B1_TOKENS) -> list[MeasuredWord]:
    """Pair each assembled word with the step its last token arrived on.

    Words carry a `pieces` count and tokens are in emission order, so walking
    both together is exact — and `sum(pieces) == len(tokens)` is asserted rather
    than assumed, because a silent mismatch would shift every word's timing by a
    piece and produce a fixture that looks plausible and is wrong.
    """
    words = json.loads(report.read_text(encoding="utf-8"))["words"]
    steps = [json.loads(line)["step"] for line in tokens.read_text(encoding="utf-8").splitlines()]

    expected = sum(w["pieces"] for w in words)
    if expected != len(steps):
        raise ValueError(
            f"b1 fixture inconsistent: {expected} pieces across words, {len(steps)} tokens"
        )

    measured: list[MeasuredWord] = []
    cursor = 0
    for word in words:
        cursor += word["pieces"]
        emitted_at = steps[cursor - 1] * FRAME_DURATION_MS
        measured.append(
            MeasuredWord(
                text=word["text"],
                start_ms=word["start_ms"],
                end_ms=word["end_ms"],
                # A word cannot be emitted before it was spoken; clamp rather
                # than trust, so a fixture edit cannot produce a negative lag.
                emitted_at_ms=max(emitted_at, word["end_ms"]),
            )
        )
    return measured


class MeasuredASRSession:
    """One stream, replaying B1's emission timing against pushed frames."""

    def __init__(self, words: Sequence[MeasuredWord], *, loop_after_ms: int | None = None) -> None:
        self._words = list(words)
        # For long-run tests: after this much stream time, start the script
        # again with its offsets shifted. None means the stream simply goes
        # quiet once the fixture is exhausted, which is itself realistic.
        self._loop_after_ms = loop_after_ms
        self._queue: asyncio.Queue[ASREvent] = asyncio.Queue()
        self._frames = 0
        self._cursor = 0
        self._cycle = 0
        self._events_emitted = 0
        self._closed = False

    @property
    def identity(self) -> AsrIdentity:
        return MEASURED_IDENTITY

    @property
    def emits_end_of_turn(self) -> bool:
        """False, like the runtime this replays.

        The `-mlx` weights carry no VAD heads (Spike B1 §4), so the segmenter
        gets its punctuation fallback — which is what makes this fixture
        exercise the *same* closing rules a real MLX meeting does.
        """
        return False

    @property
    def _stream_ms(self) -> int:
        return self._frames * FRAME_DURATION_MS

    async def push_audio(self, chunk: AudioChunk) -> None:
        self._frames += 1
        self._drain_due()

    def _drain_due(self) -> None:
        """Emit every word the real model had produced by this stream position."""
        while True:
            if self._cursor >= len(self._words):
                if self._loop_after_ms is None:
                    return
                # Restart the script one loop further along the timeline.
                self._cycle += 1
                self._cursor = 0
            offset = self._cycle * (self._loop_after_ms or 0)
            word = self._words[self._cursor]
            if word.emitted_at_ms + offset > self._stream_ms:
                return
            self._cursor += 1
            self._events_emitted += 1
            self._queue.put_nowait(
                WordEvent(
                    text=word.text,
                    start_ms=word.start_ms + offset,
                    end_ms=word.end_ms + offset,
                )
            )

    async def events(self) -> AsyncIterator[ASREvent]:
        while not self._closed:
            try:
                yield await asyncio.wait_for(self._queue.get(), timeout=0.05)
            except TimeoutError:
                continue

    async def flush(self) -> None:
        """Emit whatever the model would still have owed us.

        MLX has no flush trick (A-12 answered negatively), so this releases the
        pending words rather than pretending the runtime could be accelerated.
        """
        while self._cursor < len(self._words):
            word = self._words[self._cursor]
            self._cursor += 1
            self._events_emitted += 1
            self._queue.put_nowait(
                WordEvent(text=word.text, start_ms=word.start_ms, end_ms=word.end_ms)
            )

    async def close(self) -> None:
        self._closed = True

    def health(self) -> ASRHealth:
        transcribed = max(0, self._stream_ms - MEASURED_MODEL_DELAY_MS)
        return ASRHealth(
            healthy=not self._closed,
            lag_ms=MEASURED_MODEL_DELAY_MS,
            last_event_at_ms=None,
            events_emitted=self._events_emitted,
            transcribed_offset_ms=transcribed,
        )


class MeasuredRecognizer:
    """`StreamingRecognizer` replaying a real run's emission timing."""

    def __init__(
        self,
        words: Sequence[MeasuredWord] | None = None,
        *,
        loop_after_ms: int | None = None,
    ) -> None:
        self._words = list(words) if words is not None else load_measured_words()
        self._loop_after_ms = loop_after_ms
        self.opened_sessions: list[MeasuredASRSession] = []

    async def readiness(self) -> RecognizerReadiness:
        return RecognizerReadiness(
            state="ready", detail="replaying measured B1 timing; no model loaded"
        )

    async def open_session(self, cfg: ASRSessionConfig) -> MeasuredASRSession:
        session = MeasuredASRSession(self._words, loop_after_ms=self._loop_after_ms)
        self.opened_sessions.append(session)
        return session
