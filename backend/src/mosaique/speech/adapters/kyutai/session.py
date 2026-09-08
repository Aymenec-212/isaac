"""`ASRSession` and `StreamingRecognizer` over any Kyutai backend (spec 9.1).

Everything that is the same whichever runtime is underneath lives here: the
event queue, `health()`, the liveness check, and the fact that `FakeRecognizer`
and this are interchangeable. Only the parts that genuinely differ — how a frame
is turned into text, and what `flush()` costs — sit in the backends.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable

from mosaique.speech.adapters.kyutai.backend import KyutaiBackend
from mosaique.speech.interfaces import (
    FRAME_DURATION_MS,
    ASRErrorEvent,
    ASREvent,
    ASRHealth,
    AsrIdentity,
    ASRSessionConfig,
    AudioChunk,
    RecognizerReadiness,
)

log = logging.getLogger(__name__)

# Tech spec 9.2 says "no event for 5 s while audio is being pushed". Taken as
# written that is wrong for this model, and the difference matters: on MLX most
# steps emit nothing at all — 663 of B1's 825 were padding — so a speaker who
# pauses for six seconds would be reported as a broken recognizer.
#
# What is actually being asked is whether the runtime is still *consuming*. So
# liveness is measured on `processed_frames`, which advances on silence and
# stops only when the model really has stopped. Recorded as a deliberate
# deviation rather than a silent one. [measure]
ASR_LIVENESS_TIMEOUT_S = 5.0


class KyutaiSession:
    """One participant's stream through one backend."""

    def __init__(self, backend: KyutaiBackend, *, liveness_timeout_s: float | None = None) -> None:
        self._backend = backend
        self._liveness_timeout_s = (
            ASR_LIVENESS_TIMEOUT_S if liveness_timeout_s is None else liveness_timeout_s
        )
        self._queue: asyncio.Queue[ASREvent | None] = asyncio.Queue()
        self._events_emitted = 0
        self._last_event_at_ms: int | None = None
        self._pushed_frames = 0
        self._closed = False
        self._reported_stall = False
        self._progress_frames = 0
        self._progress_at = time.monotonic()

    async def start(self) -> None:
        await self._backend.start(self._on_event)

    @property
    def identity(self) -> AsrIdentity:
        return self._backend.identity

    @property
    def emits_end_of_turn(self) -> bool:
        return self._backend.emits_end_of_turn

    # ---- ASRSession ------------------------------------------------------

    async def push_audio(self, chunk: AudioChunk) -> None:
        if self._closed:
            raise RuntimeError("push_audio on a closed session")
        self._pushed_frames += 1
        await self._backend.push(chunk.pcm)
        self._check_liveness()

    async def events(self) -> AsyncIterator[ASREvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    async def flush(self) -> None:
        await self._backend.flush()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._backend.close()
        self._queue.put_nowait(None)

    def health(self) -> ASRHealth:
        return ASRHealth(
            healthy=not self._closed and not self._reported_stall,
            lag_ms=self.lag_ms,
            last_event_at_ms=self._last_event_at_ms,
            events_emitted=self._events_emitted,
            transcribed_offset_ms=self.transcribed_offset_ms,
        )

    # ---- derived state ---------------------------------------------------

    @property
    def lag_ms(self) -> int:
        """Audio handed over that the model has not reached yet."""
        return max(0, self._pushed_frames - self._backend.processed_frames) * FRAME_DURATION_MS

    @property
    def transcribed_offset_ms(self) -> int:
        """How far into the stream the recognizer has actually transcribed.

        Built on frames *processed*, not frames pushed, so a backend that falls
        behind is visible here. That matters more on MLX than the fake ever
        suggested: at 1.24x realised the worker genuinely does fall behind, and
        the segmenter's silence tick reads this number.
        """
        return max(0, self._backend.processed_frames * FRAME_DURATION_MS - self._backend.delay_ms)

    def _on_event(self, event: ASREvent) -> None:
        self._events_emitted += 1
        self._last_event_at_ms = int(time.time() * 1000)
        self._queue.put_nowait(event)

    def _check_liveness(self) -> None:
        """Has the runtime stopped consuming while we keep feeding it?"""
        processed = self._backend.processed_frames
        if processed != self._progress_frames:
            self._progress_frames = processed
            self._progress_at = time.monotonic()
            self._reported_stall = False
            return
        if self._reported_stall:
            return
        if time.monotonic() - self._progress_at < self._liveness_timeout_s:
            return
        self._reported_stall = True
        log.warning("asr_timeout", extra={"processed_frames": processed})
        self._on_event(
            ASRErrorEvent(
                code="ASR_TIMEOUT",
                message=(
                    f"the recognizer has not consumed a frame in {self._liveness_timeout_s:.0f}s "
                    f"while {self.lag_ms} ms of audio waits"
                ),
                fatal=False,
            )
        )


class KyutaiRecognizer:
    """`StreamingRecognizer` for Kyutai, whichever runtime is configured."""

    def __init__(self, backend_factory: Callable[[], KyutaiBackend]) -> None:
        self._backend_factory = backend_factory
        self._identity: AsrIdentity | None = None
        self._warmed: str | None = None
        self._warm_error: str | None = None

    @property
    def identity(self) -> AsrIdentity | None:
        """What the last opened session reported, for `Meeting.asr_version`.

        None until a session has been opened: the MLX identity is not fully
        known until the weights are on disk and their filename has been read.
        """
        return self._identity

    async def preload(self) -> None:
        """Warm whatever the runtime needs warmed, before the first meeting.

        A no-op for a runtime with nothing to warm; `moshi_server` connects
        per session and has nothing to do here.

        Records the outcome so `readiness()` can answer without repeating the
        work: on MLX the warm-up is a 284-second model load, and a health
        endpoint that triggered one would be a denial-of-service button.
        """
        backend = self._backend_factory()
        warm = getattr(backend, "preload", None)
        if warm is None:
            self._warmed = "nothing to warm"
            return
        try:
            await warm()
        except Exception as exc:
            # Kept, not swallowed: a failed load is exactly what `/readyz` is
            # for, and the reason belongs in the response rather than only in a
            # log line nobody reads until after the meeting.
            self._warm_error = f"{type(exc).__name__}: {exc}"
            raise
        self._warmed = "weights loaded"

    async def readiness(self) -> RecognizerReadiness:
        """Whether this runtime could take a meeting right now.

        Reports what `preload()` actually observed rather than probing again.

        `moshi_server` returns **unknown**, not ready: its readiness is a
        property of a remote server nobody has ever reached (L-27), and
        answering "ready" for a thing never checked is how a health endpoint
        becomes a liability. `/readyz` treats unknown as not-ready, so the gap
        is visible until Slice 6B implements a real probe.
        """
        if self._warm_error is not None:
            return RecognizerReadiness(state="not_ready", detail=self._warm_error)
        if self._warmed is None:
            return RecognizerReadiness(
                state="unknown", detail="preload has not run; runtime unverified"
            )
        if self._warmed == "nothing to warm":
            return RecognizerReadiness(
                state="unknown",
                detail=(
                    "this runtime has nothing to preload, so readiness is a property "
                    "of a remote server that has not been probed (Slice 6B)"
                ),
            )
        return RecognizerReadiness(state="ready", detail=self._warmed)

    async def open_session(self, cfg: ASRSessionConfig) -> KyutaiSession:
        session = KyutaiSession(self._backend_factory())
        await session.start()
        self._identity = session.identity
        return session
