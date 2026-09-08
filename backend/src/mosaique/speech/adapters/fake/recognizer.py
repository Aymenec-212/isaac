"""Deterministic recognizer used for tests and for Slices 1-3 (tech spec 9.1).

It ignores the audio content and emits a fixed script, keyed to how much audio
has been pushed. Two consequences worth stating plainly:

* it is deterministic, so the same fixture always yields the same transcript;
* it is fast-forwardable, because it advances on frames rather than wall clock.

`delay_ms` imitates the model delay Kyutai documents (~0.5 s), so latency
instrumentation built in this slice measures something realistic.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from mosaique.speech.adapters.fake.script import (
    DEFAULT_SCRIPT,
    ScriptedEndOfTurn,
    ScriptedWord,
    ScriptItem,
)
from mosaique.speech.interfaces import (
    FAKE_IDENTITY,
    FRAME_DURATION_MS,
    ASREvent,
    ASRHealth,
    AsrIdentity,
    ASRSessionConfig,
    AudioChunk,
    EndOfTurnEvent,
    RecognizerReadiness,
    WordEvent,
)

DEFAULT_MODEL_DELAY_MS = 500


class FakeASRSession:
    def __init__(
        self,
        script: Sequence[ScriptItem] = DEFAULT_SCRIPT,
        *,
        delay_ms: int = DEFAULT_MODEL_DELAY_MS,
    ) -> None:
        self._script = sorted(script, key=lambda i: i.at_ms)
        self._delay_ms = delay_ms
        self._cursor = 0
        self._stream_offset_ms = 0
        self._queue: asyncio.Queue[ASREvent | None] = asyncio.Queue()
        self._closed = False
        self._last_event_at_ms: int | None = None
        self._events_emitted = 0

    @property
    def emits_end_of_turn(self) -> bool:
        """True: the script carries `ScriptedEndOfTurn` items and emits them.

        Saying so keeps the fake's segmentation exactly as Slices 1-3 left it.
        The punctuation fallback exists for a runtime with no VAD, and turning
        it on here would silently move where the scripted phrases close.
        """
        return True

    @property
    def identity(self) -> AsrIdentity:
        """`fake/scripted@fake-none`, so a scripted transcript is never
        mistaken for one a model produced (ADR-13 consequence 3)."""
        return FAKE_IDENTITY

    @property
    def stream_offset_ms(self) -> int:
        """Audio actually received, in milliseconds. The ADR-11 clock."""
        return self._stream_offset_ms

    async def push_audio(self, chunk: AudioChunk) -> None:
        if self._closed:
            raise RuntimeError("push_audio on a closed session")
        self._stream_offset_ms += FRAME_DURATION_MS
        self._emit_due(self._stream_offset_ms - self._delay_ms)

    def _emit_due(self, up_to_ms: int) -> None:
        """Release every scripted item whose time has come, in order."""
        while self._cursor < len(self._script):
            item = self._script[self._cursor]
            if item.at_ms > up_to_ms:
                break
            self._cursor += 1
            self._last_event_at_ms = item.at_ms
            self._events_emitted += 1
            if isinstance(item, ScriptedWord):
                self._queue.put_nowait(
                    WordEvent(
                        text=item.text,
                        start_ms=item.at_ms,
                        end_ms=item.at_ms + 200,
                        confidence=0.95,
                    )
                )
            elif isinstance(item, ScriptedEndOfTurn):
                self._queue.put_nowait(
                    EndOfTurnEvent(at_ms=item.at_ms, probability=item.probability)
                )

    async def flush(self) -> None:
        """Accelerated catch-up, per blueprint D-05.


        Everything already pushed is released immediately rather than waiting
        out `delay_ms`. A real adapter asks the runtime to process faster than
        real time; the observable behaviour here is the same.
        """
        self._delay_ms = 0
        self._emit_due(self._stream_offset_ms)

    async def events(self) -> AsyncIterator[ASREvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)

    @property
    def transcribed_offset_ms(self) -> int:
        return max(0, self._stream_offset_ms - self._delay_ms)

    def health(self) -> ASRHealth:
        return ASRHealth(
            healthy=not self._closed,
            lag_ms=0,
            last_event_at_ms=self._last_event_at_ms,
            events_emitted=self._events_emitted,
            transcribed_offset_ms=self.transcribed_offset_ms,
        )


class FakeRecognizer:
    """A `StreamingRecognizer` that hands out scripted sessions."""

    def __init__(
        self,
        script: Sequence[ScriptItem] = DEFAULT_SCRIPT,
        *,
        delay_ms: int = DEFAULT_MODEL_DELAY_MS,
    ) -> None:
        self._script = script
        self._delay_ms = delay_ms
        self.opened_sessions: list[FakeASRSession] = []

    async def readiness(self) -> RecognizerReadiness:
        """Always ready: there is nothing to load and nothing to reach.

        Honest rather than lazy — the fake really can take a meeting at any
        moment, which is what makes it useful for every test that is not about
        the model.
        """
        return RecognizerReadiness(state="ready", detail="fake recognizer; no model and no network")

    async def open_session(self, cfg: ASRSessionConfig) -> FakeASRSession:
        session = FakeASRSession(self._script, delay_ms=self._delay_ms)
        self.opened_sessions.append(session)
        return session
