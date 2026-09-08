"""Product-neutral streaming ASR contract (tech spec 9.1).

Nothing outside `speech/adapters/kyutai/` may import Kyutai, moshi, or torch
types. This module is the only vocabulary the rest of the application speaks
about speech recognition, which is what lets `FakeRecognizer` carry Slices 1-3
and Kyutai arrive in Slice 4 without touching the runtime.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from mosaique.speech.interfaces.identity import AsrIdentity

# Canonical audio frame: 80 ms of 24 kHz signed 16-bit mono (tech spec 8.1).
SAMPLE_RATE_HZ = 24_000
FRAME_DURATION_MS = 80
SAMPLES_PER_FRAME = SAMPLE_RATE_HZ * FRAME_DURATION_MS // 1000  # 1920
BYTES_PER_SAMPLE = 2
FRAME_PAYLOAD_BYTES = SAMPLES_PER_FRAME * BYTES_PER_SAMPLE  # 3840
SILENCE_FRAME = b"\x00" * FRAME_PAYLOAD_BYTES


@dataclass(frozen=True)
class AudioChunk:
    """One canonical 80 ms frame handed to a recognizer."""

    pcm: bytes
    sequence: int

    def __post_init__(self) -> None:
        if len(self.pcm) != FRAME_PAYLOAD_BYTES:
            raise ValueError(f"AudioChunk must be {FRAME_PAYLOAD_BYTES} bytes, got {len(self.pcm)}")


@dataclass(frozen=True)
class WordEvent:
    """A recognized word with timings relative to the start of the ASR stream."""

    text: str
    start_ms: int
    end_ms: int | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class EndOfTurnEvent:
    """Semantic VAD signal. `probability` is compared against a tuned threshold."""

    at_ms: int
    probability: float


@dataclass(frozen=True)
class ASRErrorEvent:
    code: str
    message: str
    fatal: bool = False


ASREvent = WordEvent | EndOfTurnEvent | ASRErrorEvent


@dataclass(frozen=True)
class ASRSessionConfig:
    language: str = "fr"
    sample_rate_hz: int = SAMPLE_RATE_HZ
    correlation: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ASRHealth:
    healthy: bool
    lag_ms: int
    last_event_at_ms: int | None
    events_emitted: int = 0
    """Monotonic count of events this session has produced.

    The runtime compares it against how many it has consumed. Silence may only
    be judged when the two agree, because otherwise the words that would
    disprove the silence are still in flight.
    """

    transcribed_offset_ms: int = 0
    """How far into the stream the recognizer has actually transcribed.

    This is *not* the same as audio pushed: a streaming model runs a fixed
    delay behind (~0.5 s for Kyutai stt-1b-en_fr). Silence detection must use
    this position, because measuring silence against pushed audio would close
    a segment every time audio is pushed faster than real time — which is
    exactly what the replay harness does. Only the adapter knows its own
    delay, so only the adapter can report this.
    """


@runtime_checkable
class ASRSession(Protocol):
    """One recognizer stream, one participant audio session."""

    @property
    def identity(self) -> AsrIdentity:
        """What produced these words (ADR-13 consequence 3).

        On the interface rather than on an adapter because the runtime writes
        it to `Meeting.asr_version`, and the runtime is not allowed to know
        which adapter it holds.
        """
        ...

    @property
    def emits_end_of_turn(self) -> bool:
        """Whether this recognizer ever produces `EndOfTurnEvent`.

        Declared here rather than discovered with `getattr`, because the
        default a missing attribute would take is a segmentation decision: a
        recognizer wrongly reported as silent gets the punctuation fallback
        rule it does not need, and its segments close in different places.

        False on Kyutai's `-mlx` weights, which carry no VAD heads at all
        (Spike B1 §4) — the measurement that put this on the interface.
        """
        ...

    async def push_audio(self, chunk: AudioChunk) -> None: ...

    def events(self) -> AsyncIterator[ASREvent]: ...

    async def flush(self) -> None:
        """Drain everything already pushed and emit any pending words.

        Blueprint D-05 (the flush trick): where the runtime processes audio
        faster than real time, this asks it to catch up now rather than waiting
        out the model delay. That is what turns a ~500 ms segment-close wait
        into roughly 125 ms, so implementations should accelerate rather than
        merely push silence.
        """
        ...

    async def close(self) -> None: ...

    def health(self) -> ASRHealth: ...


@runtime_checkable
class StreamingRecognizer(Protocol):
    async def open_session(self, cfg: ASRSessionConfig) -> ASRSession: ...
