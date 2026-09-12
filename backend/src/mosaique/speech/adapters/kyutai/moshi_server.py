"""Pinned BatchedAsr protocol, isolated from WebSocket and CUDA types.

R2 protocol tests use scripted peers. Real GPU acceptance remains a separate gate.
A dropped connection ends this inference session: reconnect requires a new backend
and audio epoch. Never replay audio into fresh model state under an old clock.
"""

from __future__ import annotations

import array
import asyncio
import contextlib
import math
import sys
import time
from typing import TypeGuard

from mosaique.speech.adapters.kyutai.backend import EventSink
from mosaique.speech.adapters.kyutai.identity import DEFAULT_QUANTIZATION, moshi_server_identity
from mosaique.speech.adapters.kyutai.transport import MoshiTransport, TransportClosed
from mosaique.speech.interfaces import (
    FRAME_DURATION_MS,
    ASRErrorEvent,
    ASREvent,
    AsrIdentity,
    EndOfTurnEvent,
    WordEvent,
)

DEFAULT_HF_REPO = "kyutai/stt-1b-en_fr"
READY_TIMEOUT_S = 5.0
FLUSH_TIMEOUT_S = 4.0  # Fits the current meeting runtime's five-second outer deadline.
PAUSE_PREDICTION_HEAD_INDEX = 2  # Upstream: 0.5, 1, 2, 3 second pause heads.
ASR_DELAY_FRAMES = 6  # R1's pinned config: six 80-ms tokens, not rounded 500 ms.
TAIL_SAMPLES = 240_000  # Upstream file client: ten seconds, submitted without sleeping.


class MoshiSessionError(RuntimeError):
    """Terminal failure; callers must create a fresh inference/audio session."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def pcm_to_floats(pcm: bytes) -> list[float]:
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return [s / 32768.0 for s in samples]


def _number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _vad_probability(message: dict[str, object]) -> float | None:
    prs = message.get("prs")
    if isinstance(prs, list) and len(prs) == 4:
        value = prs[PAUSE_PREDICTION_HEAD_INDEX]
        if _number(value) and 0 <= value <= 1:
            return float(value)
    return None


class MoshiServerBackend:
    def __init__(
        self,
        transport: MoshiTransport,
        *,
        hf_repo: str = DEFAULT_HF_REPO,
        quantization: str = DEFAULT_QUANTIZATION,
        delay_ms: int = ASR_DELAY_FRAMES * FRAME_DURATION_MS,
        ready_timeout_s: float = READY_TIMEOUT_S,
        flush_timeout_s: float = FLUSH_TIMEOUT_S,
    ) -> None:
        self._transport = transport
        self._identity = moshi_server_identity(hf_repo, quantization)
        self._delay_ms = delay_ms
        self._ready_timeout_s = ready_timeout_s
        self._flush_timeout_s = flush_timeout_s
        self._emit: EventSink | None = None
        self._reader: asyncio.Task[None] | None = None
        self._steps = 0
        self._pushed = 0
        self._pending_word: WordEvent | None = None
        self._marker: asyncio.Future[None] | None = None
        self._marker_id = 0
        self._failure: MoshiSessionError | None = None
        self._started = False
        self._draining = False
        self.closed = False
        self.last_progress_at: float | None = None

    @property
    def identity(self) -> AsrIdentity:
        return self._identity

    @property
    def delay_ms(self) -> int:
        return self._delay_ms

    @property
    def emits_end_of_turn(self) -> bool:
        return True

    @property
    def processed_frames(self) -> int:
        # Synthetic tail must never advance the transcript beyond recorded audio.
        return min(self._steps, self._pushed + self._delay_ms // FRAME_DURATION_MS)

    @property
    def progressing(self) -> bool:
        return (
            not self.closed
            and self._failure is None
            and self.last_progress_at is not None
            and time.monotonic() - self.last_progress_at < 5.0
        )

    async def start(self, emit: EventSink) -> None:
        if self._started or self.closed:
            raise RuntimeError("backend is single-use")
        self._started = True
        self._emit = emit
        try:
            async with asyncio.timeout(self._ready_timeout_s):
                await self._transport.connect()
                message = await self._transport.receive()
                if message.get("type") == "Error":
                    raise self._server_error(message)
                if message.get("type") != "Ready":
                    raise MoshiSessionError("ASR_PROTOCOL_ERROR", "expected Ready before audio")
            self._reader = asyncio.create_task(self._read())
        except BaseException:
            await self.close()
            raise

    def _check(self) -> None:
        if self._failure is not None:
            raise self._failure
        if self.closed or self._reader is None:
            raise MoshiSessionError("ASR_UNAVAILABLE", "inference session is not open")

    async def push(self, pcm: bytes) -> None:
        self._check()
        if self._draining:
            raise RuntimeError("audio after terminal flush")
        await self._send({"type": "Audio", "pcm": pcm_to_floats(pcm)})
        self._pushed += 1

    async def flush(self) -> None:
        self._check()
        if self._draining:
            raise RuntimeError("flush is terminal and may run only once")
        self._draining = True
        self._marker_id += 1
        self._marker = asyncio.get_running_loop().create_future()
        try:
            async with asyncio.timeout(self._flush_timeout_s):
                await self._send({"type": "Marker", "id": self._marker_id})
                await self._send({"type": "Audio", "pcm": [0.0] * TAIL_SAMPLES})
                await self._marker
        except BaseException as exc:
            if isinstance(exc, TimeoutError):
                error = MoshiSessionError("ASR_FLUSH_TIMEOUT", "tail marker deadline exceeded")
                self._fail(error)
                raise error from exc
            raise
        finally:
            if self._marker is not None:
                if not self._marker.done():
                    self._marker.cancel()
                elif not self._marker.cancelled():
                    self._marker.exception()  # Consume an error even if send failed first.
                self._marker = None
            await self.close()

    async def close(self) -> None:
        self.closed = True
        reader, self._reader = self._reader, None
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
        if self._marker is not None and not self._marker.done():
            self._marker.cancel()
        await self._transport.close()

    async def _send(self, message: dict[str, object]) -> None:
        self._check()
        try:
            async with asyncio.timeout(self._flush_timeout_s):
                await self._transport.send(message)
        except (TransportClosed, TimeoutError) as exc:
            error = MoshiSessionError("ASR_UNAVAILABLE", "ASR send failed; fresh session required")
            self._fail(error)
            await self.close()
            raise error from exc

    async def _read(self) -> None:
        try:
            while True:
                await self._on_message(await self._transport.receive())
                if self._marker is not None and self._marker.done():
                    return
        except asyncio.CancelledError:
            raise
        except (TransportClosed, MoshiSessionError, ValueError, TypeError):
            if self._failure is None:
                self._fail(
                    MoshiSessionError(
                        "ASR_UNAVAILABLE", "ASR reader failed; fresh session required"
                    )
                )
            # Keep the pending marker's exception intact for flush's waiter.
            self.closed = True
            await self._transport.close()

    @staticmethod
    def _server_error(message: dict[str, object]) -> MoshiSessionError:
        capacity = message.get("message") == "no free channels"
        return MoshiSessionError(
            "ASR_CAPACITY_EXHAUSTED" if capacity else "ASR_RUNTIME_FAILED",
            "ASR capacity exhausted" if capacity else "ASR server reported an error",
        )

    async def _on_message(self, message: dict[str, object]) -> None:
        kind = message.get("type")
        if kind == "Step":
            # step_idx is a GLOBAL batch counter. Count this channel's messages.
            self._steps += 1
            self.last_progress_at = time.monotonic()
            probability = _vad_probability(message)
            if probability is not None:
                self._publish(
                    EndOfTurnEvent(
                        at_ms=max(0, self.processed_frames * FRAME_DURATION_MS - self._delay_ms),
                        probability=probability,
                    )
                )
        elif kind == "Word":
            self._release_pending_word()
            text, start = message.get("text"), message.get("start_time")
            if isinstance(text, str) and _number(start):
                self._pending_word = WordEvent(text=text, start_ms=int(float(start) * 1000))
        elif kind == "EndWord":
            stop = message.get("stop_time")
            if self._pending_word is not None and _number(stop):
                word, self._pending_word = self._pending_word, None
                self._publish(
                    WordEvent(
                        text=word.text, start_ms=word.start_ms, end_ms=int(float(stop) * 1000)
                    )
                )
        elif kind == "Marker":
            if (
                type(message.get("id")) is int
                and message.get("id") == self._marker_id
                and self._marker is not None
                and not self._marker.done()
            ):
                self._release_pending_word()
                self._marker.set_result(None)
        elif kind == "Error":
            error = self._server_error(message)
            self._fail(error)
            raise error

    def _fail(self, error: MoshiSessionError) -> None:
        if self._failure is None:
            self._failure = error
            self._publish(ASRErrorEvent(code=error.code, message=str(error), fatal=True))
        if self._marker is not None and not self._marker.done():
            self._marker.set_exception(error)

    def _release_pending_word(self) -> None:
        if self._pending_word is not None:
            word, self._pending_word = self._pending_word, None
            self._publish(word)

    def _publish(self, event: ASREvent) -> None:
        if self._emit is not None:
            self._emit(event)
