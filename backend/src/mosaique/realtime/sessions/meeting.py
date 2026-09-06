"""Meeting runtime (tech spec 2.1).

Consumes `IngressEvent`s, drives one ASR session per participant stream, folds
words into segments, persists finals, and publishes to a `Broadcaster`.

It imports no WebSocket, FastAPI, or Starlette type. That is the D-04 rule, and
`tests/unit/test_architecture.py` fails the build if it is ever broken.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import BinaryIO

from mosaique.observability.logging import get_logger
from mosaique.observability.metrics import METRICS
from mosaique.persistence.engine import session_scope
from mosaique.persistence.repositories.transcript import (
    AudioSessionRepository,
    SegmentRepository,
)
from mosaique.realtime.ingress import (
    Broadcaster,
    IngressAudioFrame,
    IngressError,
    IngressEvent,
    MeetingIngress,
    MeetingRef,
    ParticipantJoined,
    ParticipantLeft,
)
from mosaique.realtime.protocol.messages import (
    TranscriptDelta,
    TranscriptSegmentFinal,
)
from mosaique.realtime.sessions.participant import ParticipantSession
from mosaique.speech.audio import AudioStore
from mosaique.speech.interfaces import (
    SILENCE_FRAME,
    ASRErrorEvent,
    ASREvent,
    ASRSessionConfig,
    EndOfTurnEvent,
    StreamingRecognizer,
    WordEvent,
)
from mosaique.transcript.segmenter import (
    SegmentDelta,
    Segmenter,
    SegmenterEvent,
    SegmentFinal,
    shift,
)

log = get_logger(__name__)

# Finalization drain deadline, tech spec 11 step 3. [measure]
DRAIN_DEADLINE_S = 20.0

# How long the reader waits for the next recognizer event before checking for
# silence. Short enough to keep segment closing responsive, long enough that a
# burst of events is always drained first.
TICK_INTERVAL_S = 0.05


def _now_ms() -> int:
    return int(time.time() * 1000)


class MeetingRuntime:
    """One live meeting. Created when the first participant connects."""

    def __init__(
        self,
        *,
        meeting: MeetingRef,
        ingress: MeetingIngress,
        broadcaster: Broadcaster,
        recognizer: StreamingRecognizer,
        audio_store: AudioStore,
        started_at_ms: int,
    ) -> None:
        self.meeting = meeting
        self._ingress = ingress
        self._broadcaster = broadcaster
        self._recognizer = recognizer
        self._audio_store = audio_store
        self._started_at_ms = started_at_ms

        self._sessions: dict[str, ParticipantSession] = {}
        self._files: dict[str, BinaryIO] = {}
        self._pumps: dict[str, asyncio.Task[None]] = {}
        self._first_word_seen: set[str] = set()
        self._frame_arrival_ms: dict[str, int] = {}
        self._consumer: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        await self._ingress.start(self.meeting)
        self._consumer = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        try:
            async for event in self._ingress.events():
                await self._handle(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("ingress_consumer_failed", error_type=type(exc).__name__)
        finally:
            self._stopped.set()

    async def _handle(self, event: IngressEvent) -> None:
        if isinstance(event, ParticipantJoined):
            await self._open_participant(event)
        elif isinstance(event, IngressAudioFrame):
            self._on_frame(event)
        elif isinstance(event, ParticipantLeft):
            await self._close_participant(event.participant_id)
        elif isinstance(event, IngressError):
            log.warning("ingress_error", code=event.code, participant_id=event.participant_id)

    async def _open_participant(self, event: ParticipantJoined) -> None:
        if event.participant_id in self._sessions:
            return

        # ADR-11: the anchor is server receive time relative to meeting start.
        epoch_ms = max(0, _now_ms() - self._started_at_ms)

        async with session_scope() as db:
            first_sequence = await SegmentRepository(
                db, self.meeting.organization_id
            ).next_sequence(event.participant_id)
            await AudioSessionRepository(db, self.meeting.organization_id).create(
                audio_session_id=event.audio_session_id,
                meeting_id=self.meeting.meeting_id,
                participant_id=event.participant_id,
                epoch_ms=epoch_ms,
                audio_object_key=self._audio_store.object_key(
                    self.meeting.meeting_id, event.audio_session_id
                ),
            )

        asr = await self._recognizer.open_session(
            ASRSessionConfig(
                language="fr",
                correlation={
                    "meeting_id": self.meeting.meeting_id,
                    "participant_id": event.participant_id,
                },
            )
        )
        session = ParticipantSession(
            participant_id=event.participant_id,
            audio_session_id=event.audio_session_id,
            asr_session=asr,
            segmenter=Segmenter(first_sequence=first_sequence),
            epoch_ms=epoch_ms,
        )
        self._sessions[event.participant_id] = session
        self._files[event.participant_id] = self._audio_store.open_session(
            self.meeting.meeting_id, event.audio_session_id
        )
        self._pumps[event.participant_id] = asyncio.create_task(self._pump(session))
        log.info(
            "participant_stream_opened",
            participant_id=event.participant_id,
            epoch_ms=epoch_ms,
        )

    def _on_frame(self, frame: IngressAudioFrame) -> None:
        session = self._sessions.get(frame.participant_id)
        if session is None:
            return
        self._frame_arrival_ms.setdefault(frame.participant_id, _now_ms())
        session.accept(frame.seq, frame.pcm, _now_ms())

    # ---- the per-participant pipeline ------------------------------------

    async def _pump(self, session: ParticipantSession) -> None:
        """Queue -> recognizer -> segmenter -> broadcast + persist."""
        reader = asyncio.create_task(self._read_events(session))
        try:
            while True:
                frame = await session.next_frame()
                if frame is None:
                    break
                padding = await session.push(frame)
                self._write_audio(session, frame.pcm, padding)
                # Pushing a frame never awaits anything real, so without this
                # the pump can drain a full queue without once yielding and
                # starve the reader that is turning those frames into text.
                await asyncio.sleep(0)
                # Silence closes a segment; that check needs a tick (tech spec 9.3).
                await self._emit(session, session.segmenter.on_tick(session.stream_offset_ms))
        except asyncio.CancelledError:
            raise
        finally:
            reader.cancel()

    def _write_audio(self, session: ParticipantSession, pcm: bytes, padding: int) -> None:
        """Padding goes to the file too, so byte offset maps to session time."""
        handle = self._files.get(session.participant_id)
        if handle is None:
            return
        if padding:
            handle.write(SILENCE_FRAME * padding)
        handle.write(pcm)

    async def _read_events(self, session: ParticipantSession) -> None:
        """Single owner of the segmenter: recognizer events in, segments out.

        The silence tick lives here rather than in the frame pump for a reason.
        Ticking from the pump would compare the segmenter's last word against
        audio that has been *pushed*, and when audio arrives faster than real
        time — every replay, every buffered reconnect — the recognizer's events
        are still queued, so every phrase would be split at the first tick.
        Waiting briefly for the next event and only then ticking means the tick
        fires exactly when the reader has caught up.
        """
        events = session.asr_session.events()
        pending: asyncio.Task[ASREvent] | None = None
        consumed = 0
        try:
            while True:
                if pending is None:
                    # Held across ticks rather than re-created: `wait_for` would
                    # cancel the pending `__anext__`, which closes the generator
                    # and silently ends the stream after the first tick.
                    pending = asyncio.ensure_future(anext(events))

                done, _ = await asyncio.wait({pending}, timeout=TICK_INTERVAL_S)
                if not done:
                    # Silence is judged in *stream* time, but this timeout is
                    # wall time. When audio arrives faster than real time — any
                    # replay, any buffered reconnect — seconds of stream can
                    # pass in a 50 ms wait, so the transcribed offset alone
                    # would fabricate silences that never happened. Only tick
                    # once the recognizer has nothing left queued; until then
                    # the words that disprove the silence are simply unread.
                    health = session.asr_session.health()
                    if health.events_emitted == consumed:
                        await self._emit(
                            session,
                            session.segmenter.on_tick(health.transcribed_offset_ms),
                        )
                    continue

                try:
                    event = pending.result()
                except StopAsyncIteration:
                    return
                finally:
                    pending = None

                consumed += 1
                await self._dispatch(session, event)
        finally:
            if pending is not None:
                pending.cancel()

    async def _dispatch(self, session: ParticipantSession, event: ASREvent) -> None:
        if isinstance(event, WordEvent):
            if session.participant_id not in self._first_word_seen:
                self._first_word_seen.add(session.participant_id)
                arrival = self._frame_arrival_ms.get(session.participant_id)
                if arrival is not None:
                    METRICS.first_word_latency(_now_ms() - arrival)
            await self._emit(session, session.segmenter.on_word(event))
        elif isinstance(event, EndOfTurnEvent):
            await self._emit(session, session.segmenter.on_end_of_turn(event))
        elif isinstance(event, ASRErrorEvent):
            log.warning("asr_error", code=event.code, fatal=event.fatal)

    async def _emit(self, session: ParticipantSession, events: Sequence[SegmenterEvent]) -> None:
        for raw in events:
            event = shift(raw, session.epoch_ms)
            if isinstance(event, SegmentDelta):
                await self._broadcaster.publish(
                    self.meeting.meeting_id,
                    TranscriptDelta(
                        participant_id=session.participant_id,
                        sequence=event.sequence,
                        revision=event.revision,
                        text=event.text,
                        start_ms=event.start_ms,
                    ).model_dump(),
                )
            elif isinstance(event, SegmentFinal):
                await self._persist_and_publish(session, event)

    async def _persist_and_publish(self, session: ParticipantSession, event: SegmentFinal) -> None:
        async with session_scope() as db:
            segment_id = await SegmentRepository(db, self.meeting.organization_id).add_final(
                meeting_id=self.meeting.meeting_id,
                participant_id=session.participant_id,
                audio_session_id=session.audio_session_id,
                sequence=event.sequence,
                start_ms=event.start_ms,
                end_ms=event.end_ms,
                text=event.text,
                words=event.words,
            )
        await self._broadcaster.publish(
            self.meeting.meeting_id,
            TranscriptSegmentFinal(
                participant_id=session.participant_id,
                sequence=event.sequence,
                revision=event.revision,
                segment_id=segment_id,
                text=event.text,
                start_ms=event.start_ms,
                end_ms=event.end_ms,
            ).model_dump(),
        )

    # ---- finalization ----------------------------------------------------

    async def drain(self, deadline_s: float = DRAIN_DEADLINE_S) -> None:
        """Tech spec 11 step 3: drain, flush, close open segments.

        `flush()` is the D-05 accelerated catch-up rather than a wait, which is
        what keeps this deadline generous instead of tight.
        """
        for session in self._sessions.values():
            await session.stop()

        if self._pumps:
            await asyncio.wait(self._pumps.values(), timeout=deadline_s)

        for session in self._sessions.values():
            try:
                await asyncio.wait_for(session.asr_session.flush(), timeout=5.0)
                for _ in range(50):
                    await asyncio.sleep(0.01)
                    if not session.segmenter.has_open_segment:
                        break
                await self._emit(session, session.segmenter.close_open())
                await session.asr_session.close()
            except TimeoutError:
                log.warning("finalize_drain_timeout", participant_id=session.participant_id)

        async with session_scope() as db:
            repo = AudioSessionRepository(db, self.meeting.organization_id)
            for session in self._sessions.values():
                await repo.finish(
                    session.audio_session_id,
                    frames_received=session.frames_received,
                    frames_dropped=session.frames_dropped,
                )

        for handle in self._files.values():
            handle.close()
        self._files.clear()

    async def _close_participant(self, participant_id: str) -> None:
        session = self._sessions.get(participant_id)
        if session is None:
            return
        await session.stop()

    async def stop(self) -> None:
        for pump in self._pumps.values():
            pump.cancel()
        if self._consumer is not None:
            self._consumer.cancel()
        await self._ingress.stop()
        for handle in self._files.values():
            handle.close()
        self._files.clear()
