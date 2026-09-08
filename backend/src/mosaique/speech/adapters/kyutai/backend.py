"""The seam between one Kyutai runtime and the `ASRSession` wrapped around it.

ADR-13 made the runtime a configuration axis: the model is fixed, and `mlx`,
`moshi_server` and `fake` are three ways of running it. This Protocol is where
that axis lives. Everything the session does — queueing events, health, the
ASR-timeout, `flush()` semantics — is written once against this, so adding a
runtime is one file and no changes upstream.

Nothing here imports a model library or a transport. `test_architecture.py`
enforces both, and a backend that needed either in this file would be a sign
the seam is in the wrong place.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from mosaique.speech.interfaces import ASREvent, AsrIdentity

# Events travel from a backend to its session through this, never by return
# value: the MLX backend produces them on a worker thread and moshi-server
# produces them from a socket reader, so neither can hand them back from
# `push`. Implementations must be safe to call from the event loop thread only;
# a backend on another thread marshals first.
EventSink = Callable[[ASREvent], None]


@runtime_checkable
class KyutaiBackend(Protocol):
    """One recognizer stream against one runtime."""

    @property
    def identity(self) -> AsrIdentity:
        """Model, runtime and quantization, for `Meeting.asr_version`."""
        ...

    @property
    def delay_ms(self) -> int:
        """How far the runtime runs behind the audio it has been given.

        500 ms for `stt-1b-en_fr`, read from the build's `config.json` rather
        than assumed (Spike B1 §3).
        """
        ...

    @property
    def emits_end_of_turn(self) -> bool:
        """Whether this runtime produces `EndOfTurnEvent` at all.

        False on MLX: the `-mlx` weights carry no VAD heads, which is why the
        segmenter grew a punctuation rule in Slice 4. The segmenter is told, so
        it can stop relying on a signal that will never arrive.
        """
        ...

    @property
    def processed_frames(self) -> int:
        """Frames the runtime has actually run through the model.

        Not frames pushed. The difference is the backlog, and it is what
        `transcribed_offset_ms` and the liveness check are built on — a
        recognizer that has stopped consuming looks exactly like a quiet
        speaker if you only count what went in.
        """
        ...

    async def start(self, emit: EventSink) -> None: ...

    async def push(self, pcm: bytes) -> None:
        """Hand over one canonical 80 ms frame (tech spec 8.1)."""
        ...

    async def flush(self) -> None:
        """Drain everything pushed so far and emit any word still pending.

        What this costs differs by runtime, and the difference is measured, not
        assumed: see `MlxBackend.flush` and `MoshiServerBackend.flush`.
        """
        ...

    async def close(self) -> None: ...
