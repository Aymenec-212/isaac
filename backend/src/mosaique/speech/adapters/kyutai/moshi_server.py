"""Kyutai STT served by `moshi-server`, reached over an injected transport.

This is the deployment runtime (ADR-13) and the only one that can answer A-3
and A-4. **Nothing here has ever run against a real server**: that needs a CUDA
host, which is Spike B2's blocker and Slice 6's. What is tested is every line
that does not need one — the message translation, the reconnect schedule, the
health arithmetic — against a fake transport.

The wire protocol, from `moshi-server`'s own client script:

    ->  {"type": "Audio",  "pcm": [float, ...]}    one frame, -1.0..1.0
    ->  {"type": "Marker", "id": int}              "tell me when you get here"
    <-  {"type": "Step",   ...}                    per-step VAD and progress
    <-  {"type": "Word",   "text": str, "start_time": float}
    <-  {"type": "EndWord", "stop_time": float}
    <-  {"type": "Marker", "id": int}              everything before it is done

Two differences from MLX are worth stating, because they change what the
segmenter can rely on:

* words arrive whole, with a start time, and `EndWord` gives a real `end_ms`.
  No piece reassembly, and no inferred end.
* `Step` carries a VAD signal, so `EndOfTurnEvent` exists here and the §9.3
  `end_of_turn_threshold` stops being dead code. That is also where it first
  becomes measurable.

`Marker` is the D-05 flush trick expressed in the protocol: send one, wait for
it to come back, and everything pushed before it has been transcribed. Whether
that is *fast* depends on the server having throughput to spare, which is
exactly what B1 showed MLX does not and B2 has yet to show CUDA does.
"""

from __future__ import annotations

import array
import asyncio
import logging

from mosaique.speech.adapters.kyutai.backend import EventSink
from mosaique.speech.adapters.kyutai.backoff import delays
from mosaique.speech.adapters.kyutai.identity import (
    DEFAULT_QUANTIZATION,
    moshi_server_identity,
)
from mosaique.speech.adapters.kyutai.transport import MoshiTransport, TransportClosed
from mosaique.speech.interfaces import (
    FRAME_DURATION_MS,
    ASRErrorEvent,
    ASREvent,
    AsrIdentity,
    EndOfTurnEvent,
    WordEvent,
)

log = logging.getLogger(__name__)

DEFAULT_HF_REPO = "kyutai/stt-1b-en_fr"
FLUSH_MARKER_ID = 1
FLUSH_TIMEOUT_S = 10.0

# `Step` messages carry the VAD probability under one of these keys depending
# on the server build. Tried in order; a build that uses none simply produces no
# end-of-turn events, which the segmenter already copes with because MLX does
# the same.
VAD_KEYS = ("prs", "pause_prediction", "vad")


def pcm_to_floats(pcm: bytes) -> list[float]:
    """Canonical s16le frame to the float list the server expects."""
    samples = array.array("h")
    samples.frombytes(pcm)
    return [s / 32768.0 for s in samples]


def _vad_probability(message: dict[str, object]) -> float | None:
    for key in VAD_KEYS:
        value = message.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, list) and value:
            last = value[-1]
            if isinstance(last, (int, float)) and not isinstance(last, bool):
                return float(last)
    return None


class MoshiServerBackend:
    """One `moshi-server` stream, with a bounded reconnect (tech spec 9.2)."""

    def __init__(
        self,
        transport: MoshiTransport,
        *,
        hf_repo: str = DEFAULT_HF_REPO,
        quantization: str = DEFAULT_QUANTIZATION,
        delay_ms: int = 500,
    ) -> None:
        self._transport = transport
        self._identity = moshi_server_identity(hf_repo, quantization)
        self._delay_ms = delay_ms
        self._emit: EventSink | None = None
        self._reader: asyncio.Task[None] | None = None
        self._processed = 0
        self._pending_word: WordEvent | None = None
        self._marker: asyncio.Future[None] | None = None
        self._closing = False

    # ---- KyutaiBackend ---------------------------------------------------

    @property
    def identity(self) -> AsrIdentity:
        return self._identity

    @property
    def delay_ms(self) -> int:
        return self._delay_ms

    @property
    def emits_end_of_turn(self) -> bool:
        """True: `Step` carries a VAD signal. Unverified against a real server."""
        return True

    @property
    def processed_frames(self) -> int:
        return self._processed

    async def start(self, emit: EventSink) -> None:
        self._emit = emit
        await self._transport.connect()
        self._reader = asyncio.create_task(self._read())

    async def push(self, pcm: bytes) -> None:
        await self._send({"type": "Audio", "pcm": pcm_to_floats(pcm)})

    async def flush(self) -> None:
        """Send a Marker and wait for it to come back (D-05, in the protocol)."""
        loop = asyncio.get_running_loop()
        self._marker = loop.create_future()
        await self._send({"type": "Marker", "id": FLUSH_MARKER_ID})
        try:
            await asyncio.wait_for(asyncio.shield(self._marker), timeout=FLUSH_TIMEOUT_S)
        except TimeoutError:
            log.warning("moshi_server_flush_marker_timeout")
        finally:
            self._marker = None
        self._release_pending_word()

    async def close(self) -> None:
        self._closing = True
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
        await self._transport.close()

    # ---- wire ------------------------------------------------------------

    async def _send(self, message: dict[str, object]) -> None:
        """Send, reconnecting a bounded number of times (tech spec 9.2).

        Bounded is the point. A stream that retries forever looks healthy from
        the outside while transcribing nothing, so once the schedule is spent
        the failure is reported and the runtime can mark the stream
        `unavailable` and keep recording audio (spec 8.4).
        """
        try:
            await self._transport.send(message)
            return
        except TransportClosed:
            pass
        for delay in delays():
            await asyncio.sleep(delay)
            try:
                await self._transport.connect()
                await self._transport.send(message)
                if self._reader is None or self._reader.done():
                    self._reader = asyncio.create_task(self._read())
                log.info("moshi_server_reconnected")
                return
            except TransportClosed:
                continue
        self._publish(
            ASRErrorEvent(
                code="ASR_UNAVAILABLE",
                message="moshi-server did not accept a reconnect within the bounded schedule",
                fatal=True,
            )
        )

    async def _read(self) -> None:
        try:
            while True:
                await self._on_message(await self._transport.receive())
        except (TransportClosed, asyncio.CancelledError):
            if not self._closing:
                log.warning("moshi_server_reader_stopped")
            raise

    async def _on_message(self, message: dict[str, object]) -> None:
        kind = message.get("type")
        if kind == "Step":
            self._processed += 1
            probability = _vad_probability(message)
            if probability is not None:
                self._publish(
                    EndOfTurnEvent(
                        at_ms=max(0, self._processed * FRAME_DURATION_MS - self._delay_ms),
                        probability=probability,
                    )
                )
        elif kind == "Word":
            # A word is held until `EndWord` gives it a stop time. Emitting it
            # early would mean an end_ms that a later message contradicts, and
            # a contradicted field is a retraction by another name (X-14).
            self._release_pending_word()
            text = message.get("text")
            start = message.get("start_time")
            if isinstance(text, str) and isinstance(start, (int, float)):
                self._pending_word = WordEvent(
                    text=text, start_ms=int(float(start) * 1000), end_ms=None, confidence=None
                )
        elif kind == "EndWord":
            stop = message.get("stop_time")
            if self._pending_word is not None and isinstance(stop, (int, float)):
                word = self._pending_word
                self._pending_word = None
                self._publish(
                    WordEvent(
                        text=word.text,
                        start_ms=word.start_ms,
                        end_ms=int(float(stop) * 1000),
                        confidence=None,
                    )
                )
        elif kind == "Marker":
            self._release_pending_word()
            if self._marker is not None and not self._marker.done():
                self._marker.set_result(None)
        elif kind == "Error":
            self._publish(
                ASRErrorEvent(code="ASR_RUNTIME_FAILED", message=str(message.get("message", "")))
            )

    def _release_pending_word(self) -> None:
        """Emit a word whose `EndWord` never came, rather than losing it."""
        if self._pending_word is not None:
            word = self._pending_word
            self._pending_word = None
            self._publish(word)

    def _publish(self, event: ASREvent) -> None:
        if self._emit is not None:
            self._emit(event)
