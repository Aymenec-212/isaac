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
from dataclasses import dataclass
from typing import BinaryIO

from mosaique.domain.ids import new_id
from mosaique.observability.latency import LatencyDecomposition
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
    ParticipantAudioState,
    ParticipantJoined,
    ParticipantLeft,
    ResumeInfo,
)
from mosaique.realtime.protocol.messages import (
    ParticipantEvent,
    ParticipantSpeaking,
    StreamStatus,
    TranscriptDelta,
    TranscriptSegmentFinal,
)
from mosaique.realtime.sessions.participant import (
    GAP_MARKER_MS,
    MAX_PADDING_FRAMES,
    OVERLOAD_FAILURE_S,
    ParticipantSession,
)
from mosaique.speech.audio import AudioStore
from mosaique.speech.interfaces import (
    FAKE_IDENTITY,
    FRAME_DURATION_MS,
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
    WordTiming,
    shift,
)

log = get_logger(__name__)


@dataclass(frozen=True)
class _PendingSegment:
    """A final segment on its way to the database, held if it cannot get there."""

    segment_id: str
    participant_id: str
    audio_session_id: str
    sequence: int
    start_ms: int
    end_ms: int
    text: str
    words: list[WordTiming]
    status: str


# Finalization drain deadline, tech spec 11 step 3. [measure]
DRAIN_DEADLINE_S = 20.0

# How long a participant's stream survives losing its transport, tech spec 7.4.
# The ASR session and the segmenter are held open for this long, so a client
# that reconnects inside the window continues its segment rather than splitting
# it. [measure]
RECONNECT_GRACE_S = 30.0

# Blueprint D-02: audio silent for this long closes the AudioSession, whether
# the participant muted or their network stalled. Resuming opens a new one with
# a fresh server anchor, which bounds silence padding at ~1.4 MB per pause
# instead of writing minutes of zeroes. [measure]
IDLE_CLOSE_S = 30.0

# How often the runtime looks for streams that have gone quiet.
IDLE_SWEEP_S = 1.0

# Tech spec 14.1: how many final segments the runtime will hold while the
# database is unreachable before it stops claiming the transcript is safe. The
# audio file keeps being written throughout, so nothing is lost outright — but
# memory is not the record (ADR-05), and pretending otherwise indefinitely
# would be a lie the client cannot see.
PERSISTENCE_BUFFER_MAX = 200

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
        # The roster is built from ingress events alone. The runtime never asks
        # the transport how many sockets exist, which is what keeps blueprint
        # D-04 honest once there is more than one participant.
        self._roster: dict[str, str] = {}
        self._speaking: set[str] = set()
        # Streams whose transport has gone but whose grace has not expired.
        self._grace: dict[str, asyncio.Task[None]] = {}
        self._files: dict[str, BinaryIO] = {}
        self._pumps: dict[str, asyncio.Task[None]] = {}
        self._first_word_seen: set[str] = set()
        self._frame_arrival_ms: dict[str, int] = {}
        self._file_frames: dict[str, int] = {}
        self._stream_status: dict[str, str] = {}
        self._pending: list[_PendingSegment] = []
        # Slice 4: where the time goes, hop by hop. Held per meeting rather
        # than globally so one meeting's numbers are readable on their own.
        self.latency = LatencyDecomposition()
        # What produced this meeting's words (ADR-13 consequence 3). Read off
        # the first ASR session opened and written at finalization; the fake
        # answers too, so the column is never NULL and never ambiguous.
        self._asr_version: str = FAKE_IDENTITY.truncated()
        # One writer at a time. Every participant's pump persists through the
        # same buffer, and without this two of them interleave around the
        # `await`: the first snapshots the buffer, writes it, and clears a
        # segment the second appended in between — which is then never written
        # by anyone, though it has already been broadcast.
        self._persist_lock = asyncio.Lock()
        self._consumer: asyncio.Task[None] | None = None
        self._idle_sweep: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    @property
    def asr_version(self) -> str:
        """What produced this meeting's words, for `Meeting.asr_version`."""
        return self._asr_version

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        await self._ingress.start(self.meeting)
        self._consumer = asyncio.create_task(self._consume())
        self._idle_sweep = asyncio.create_task(self._sweep_idle())

    async def _sweep_idle(self) -> None:
        """Close AudioSessions that have gone quiet (blueprint D-02).

        A mute and a network stall look the same from here, and D-02 wants the
        same answer for both: past `IDLE_CLOSE_S`, stop the session rather than
        pad silence into it indefinitely. The participant stays; their next
        frame opens a new AudioSession with a fresh anchor.
        """
        try:
            while True:
                await asyncio.sleep(IDLE_SWEEP_S)
                for participant_id in list(self._sessions):
                    session = self._sessions.get(participant_id)
                    if session is None or session.closed:
                        continue
                    if session.idle_for_s() < IDLE_CLOSE_S:
                        continue
                    await self._close_idle_stream(participant_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("idle_sweep_failed", error_type=type(exc).__name__)

    async def _close_idle_stream(self, participant_id: str) -> None:
        session = self._sessions.pop(participant_id, None)
        if session is None:
            return
        await session.stop()
        pump = self._pumps.pop(participant_id, None)
        if pump is not None:
            await asyncio.wait({pump}, timeout=5.0)
        await self._finalize_session(session)
        await self._set_speaking(participant_id, False)
        log.info(
            "audio_session_closed_idle",
            participant_id=participant_id,
            audio_session_id=session.audio_session_id,
        )

    async def _set_paused(self, participant_id: str, paused: bool) -> None:
        """Mute is a statement about intent, not a fault (blueprint R-1)."""
        session = self._sessions.get(participant_id)
        if session is None:
            return
        session.paused = paused
        if paused:
            await self._set_speaking(participant_id, False)
        log.info("participant_audio_state", participant_id=participant_id, paused=paused)

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
            await self._on_frame(event)
        elif isinstance(event, ParticipantLeft):
            await self._close_participant(event.participant_id)
        elif isinstance(event, ParticipantAudioState):
            await self._set_paused(event.participant_id, event.paused)
        elif isinstance(event, IngressError):
            log.warning("ingress_error", code=event.code, participant_id=event.participant_id)

    def resume_info(self, participant_id: str) -> ResumeInfo:
        """What the gateway needs to answer a `hello` (tech spec 7.4).

        Read-only, and deliberately the *only* thing the transport may ask the
        runtime. It says whether this participant still has a live stream — so
        `hello.ok` can set `resume` — and how far its sequence got, so the
        gateway can go on rejecting duplicates across a reconnect instead of
        starting again from -1 and letting a replayed buffer through.
        """
        session = self._sessions.get(participant_id)
        if session is None:
            return ResumeInfo(resuming=False, last_sequence=-1)
        return ResumeInfo(resuming=True, last_sequence=session.last_sequence)

    async def _open_participant(self, event: ParticipantJoined) -> None:
        if event.participant_id in self._sessions:
            await self._resume_participant(event)
            return
        await self._open_stream(event.participant_id, event.audio_session_id)
        await self._announce(event)

    async def _open_stream(self, participant_id: str, audio_session_id: str) -> None:
        """Start one AudioSession for a participant.

        Called on join, and again after an idle close (D-02) when the person
        starts speaking after a long mute. The segmenter's first sequence comes
        from the database, so a second AudioSession continues the participant's
        numbering rather than restarting it.
        """
        # ADR-11: the anchor is server receive time relative to meeting start.
        epoch_ms = max(0, _now_ms() - self._started_at_ms)

        async with session_scope() as db:
            first_sequence = await SegmentRepository(
                db, self.meeting.organization_id
            ).next_sequence(participant_id)
            await AudioSessionRepository(db, self.meeting.organization_id).create(
                audio_session_id=audio_session_id,
                meeting_id=self.meeting.meeting_id,
                participant_id=participant_id,
                epoch_ms=epoch_ms,
                audio_object_key=self._audio_store.object_key(
                    self.meeting.meeting_id, audio_session_id
                ),
            )

        asr = await self._recognizer.open_session(
            ASRSessionConfig(
                language="fr",
                correlation={
                    "meeting_id": self.meeting.meeting_id,
                    "participant_id": participant_id,
                },
            )
        )
        identity = asr.identity
        self._asr_version = identity.truncated()
        session = ParticipantSession(
            participant_id=participant_id,
            audio_session_id=audio_session_id,
            asr_session=asr,
            segmenter=Segmenter(
                first_sequence=first_sequence,
                # Spike B1 §4: the MLX weights emit no end-of-turn signal at
                # all, so on that runtime punctuation is the only boundary
                # marker there is. Where a runtime does emit one, both rules
                # are live and whichever fires first wins.
                close_on_sentence_end=not getattr(asr, "emits_end_of_turn", False),
            ),
            epoch_ms=epoch_ms,
        )
        self._sessions[participant_id] = session
        self._files[participant_id] = self._audio_store.open_session(
            self.meeting.meeting_id, audio_session_id
        )
        self._pumps[participant_id] = asyncio.create_task(self._pump(session))
        log.info(
            "participant_stream_opened",
            participant_id=participant_id,
            audio_session_id=audio_session_id,
            epoch_ms=epoch_ms,
        )

    async def _resume_participant(self, event: ParticipantJoined) -> None:
        """A `hello` arrived for a stream that is still alive (tech spec 7.4).

        Nothing is rebuilt. The ASR session, the segmenter and the audio file
        keep going, and the runtime keeps its own `audio_session_id` rather
        than the one the new socket minted — which is what makes a reconnect
        continue the segment instead of starting a new one. Frames the client
        buffered while it was away are accepted because their `seq` continues
        the sequence the session already has.
        """
        grace = self._grace.pop(event.participant_id, None)
        if grace is not None:
            grace.cancel()
        session = self._sessions[event.participant_id]
        session.reconnected()
        await self._broadcaster.publish(
            self.meeting.meeting_id,
            ParticipantEvent(
                type="participant.joined",
                participant_id=event.participant_id,
                display_name=self._roster.get(event.participant_id, event.display_name),
            ).model_dump(),
        )
        log.info(
            "participant_stream_resumed",
            participant_id=event.participant_id,
            last_sequence=session.last_sequence,
        )

    async def _announce(self, event: ParticipantJoined) -> None:
        """Tell the newcomer who is already here, then tell everyone about them.

        Replaying the roster to the joining socket rather than inventing a
        separate roster message keeps one message shape for the client to
        handle, and makes a late join look exactly like a live one.
        """
        for participant_id, display_name in self._roster.items():
            await self._broadcaster.send_to(
                event.participant_id,
                ParticipantEvent(
                    type="participant.joined",
                    participant_id=participant_id,
                    display_name=display_name,
                ).model_dump(),
            )
        self._roster[event.participant_id] = event.display_name
        await self._broadcaster.publish(
            self.meeting.meeting_id,
            ParticipantEvent(
                type="participant.joined",
                participant_id=event.participant_id,
                display_name=event.display_name,
            ).model_dump(),
        )

    async def _on_frame(self, frame: IngressAudioFrame) -> None:
        session = self._sessions.get(frame.participant_id)
        if session is None:
            # Audio after an idle close: the person is still in the meeting,
            # they just stopped talking for a while (D-02). Open a new
            # AudioSession with a fresh anchor rather than dropping the frame.
            # The id is minted here, not taken from the frame, because the
            # socket's id already belongs to the AudioSession we closed.
            if frame.participant_id not in self._roster:
                return
            await self._open_stream(frame.participant_id, new_id())
            session = self._sessions[frame.participant_id]
            log.info("audio_session_reopened", participant_id=frame.participant_id)
        if session.paused:
            # A frame is the clearest possible statement that they are back.
            session.paused = False
        self._frame_arrival_ms.setdefault(frame.participant_id, _now_ms())
        self.latency.on_gateway_recv(frame.participant_id, frame.seq, frame.capture_ms)

        # Tech spec 8.4: the audio file is written here, on arrival, and not in
        # the pump. A frame the ASR queue has no room for is still this
        # participant's audio, and the promise is that a skipped span stays
        # recoverable from disk even though it is never transcribed.
        self._write_arrival(session, frame.seq, frame.pcm)

        # Tech spec 8.3: frames that never arrived are padded with silence so
        # the timeline stays true, but a long run of them is marked rather than
        # left as an unexplained silence in the middle of someone talking.
        missing_from = session.last_sequence + 1
        missing = frame.seq - missing_from
        session.accept(frame.seq, frame.pcm, _now_ms())
        if missing * FRAME_DURATION_MS > GAP_MARKER_MS:
            await self._emit_gap(session, missing_from, frame.seq - 1)

        await self._update_stream_status(session)

    # ---- the per-participant pipeline ------------------------------------

    def _write_arrival(self, session: ParticipantSession, seq: int, pcm: bytes) -> None:
        """Write one frame to the audio file at its sequence position.

        Padding any missing sequences keeps the file exactly seq-indexed, which
        is what makes `byte_offset = session_ms * BYTES_PER_MS` hold and FR-11
        navigation pure arithmetic (blueprint D-02).
        """
        handle = self._files.get(session.participant_id)
        if handle is None:
            return
        written = self._file_frames.get(session.participant_id, 0)
        if seq < written:
            return  # a duplicate; the sequence is already on disk
        padding = min(seq - written, MAX_PADDING_FRAMES)
        if padding:
            handle.write(SILENCE_FRAME * padding)
        handle.write(pcm)
        self._file_frames[session.participant_id] = seq + 1

    async def _update_stream_status(self, session: ParticipantSession) -> None:
        """Map queue depth onto the five states of tech spec 8.4."""
        if session.overloaded_for_s() >= OVERLOAD_FAILURE_S:
            await self._fail_stream(session)
            return

        span = session.take_skipped_span()
        if span is not None:
            await self._emit_gap(session, *span)

        if session.paused:
            status = "listening"
        elif session.queue_full or session.lagging:
            status = "delayed"
        else:
            status = "transcribing"
        await self._publish_status(session.participant_id, status, session.lag_ms)

    async def _publish_status(self, participant_id: str, status: str, lag_ms: int = 0) -> None:
        """Publish only on a change; the depth moves every 80 ms."""
        if self._stream_status.get(participant_id) == status:
            return
        self._stream_status[participant_id] = status
        await self._broadcaster.publish(
            self.meeting.meeting_id,
            StreamStatus(
                participant_id=participant_id,
                status=status,  # type: ignore[arg-type]
                lag_ms=lag_ms,
            ).model_dump(),
        )

    async def _emit_gap(self, session: ParticipantSession, first_seq: int, last_seq: int) -> None:
        """One visible marker for a run of audio that was never transcribed."""
        METRICS.frames_skipped(last_seq - first_seq + 1)
        log.warning(
            "asr_frames_skipped",
            participant_id=session.participant_id,
            frames=last_seq - first_seq + 1,
        )
        for event in session.segmenter.insert_gap(
            first_seq * FRAME_DURATION_MS, (last_seq + 1) * FRAME_DURATION_MS
        ):
            shifted = shift(event, session.epoch_ms)
            if isinstance(shifted, SegmentFinal):
                await self._persist_and_publish(session, shifted)

    async def _fail_stream(self, session: ParticipantSession) -> None:
        """Sustained overload: stop transcribing, keep recording (spec 8.4)."""
        if self._stream_status.get(session.participant_id) == "unavailable":
            return
        await self._publish_status(session.participant_id, "unavailable")
        span = session.take_skipped_span()
        if span is not None:
            await self._emit_gap(session, *span)
        log.error("stream_unavailable", participant_id=session.participant_id)

    async def _pump(self, session: ParticipantSession) -> None:
        """Queue -> recognizer -> segmenter -> broadcast + persist."""
        reader = asyncio.create_task(self._read_events(session))
        try:
            while True:
                frame = await session.next_frame()
                if frame is None:
                    break
                self.latency.on_dequeue(session.participant_id, frame.seq)
                await session.push(frame)
                # Pushing a frame never awaits anything real, so without this
                # the pump can drain a full queue without once yielding and
                # starve the reader that is turning those frames into text.
                await asyncio.sleep(0)
                # No tick here. `stream_offset_ms` is audio *pushed*, which runs
                # ahead of what the recognizer has transcribed by the model
                # delay, so ticking on it compares two different clocks and
                # splits a phrase whenever the reader is behind — which is
                # exactly what a replay makes happen. `_read_events` owns the
                # tick, and does it against `transcribed_offset_ms` only once
                # the reader has caught up (ADR-11).
        except asyncio.CancelledError:
            raise
        finally:
            reader.cancel()

    async def _read_events(self, session: ParticipantSession) -> None:
        """Single owner of the segmenter: recognizer events in, segments out.

        "Single owner" is literal, and the frame pump must not tick it.

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
            self.latency.on_first_event(session.participant_id, event.start_ms, FRAME_DURATION_MS)
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

    async def _set_speaking(self, participant_id: str, speaking: bool) -> None:
        """Publish only on a transition, so the panel does not flicker."""
        if speaking == (participant_id in self._speaking):
            return
        self._speaking.symmetric_difference_update({participant_id})
        await self._broadcaster.publish(
            self.meeting.meeting_id,
            ParticipantSpeaking(participant_id=participant_id, active=speaking).model_dump(),
        )

    async def _emit(self, session: ParticipantSession, events: Sequence[SegmenterEvent]) -> None:
        for raw in events:
            event = shift(raw, session.epoch_ms)
            if isinstance(event, SegmentDelta):
                await self._set_speaking(session.participant_id, True)
                self.latency.on_broadcast(session.participant_id)
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
                await self._set_speaking(session.participant_id, False)
                await self._persist_and_publish(session, event)

    async def _persist_and_publish(self, session: ParticipantSession, event: SegmentFinal) -> None:
        # A gap is stored as a segment with its own status so a reader can tell
        # "nobody spoke here" from "we could not transcribe this" (spec 8.4).
        status = "gap" if event.reason == "gap" else "final"
        segment_id = new_id()
        pending = _PendingSegment(
            segment_id=segment_id,
            participant_id=session.participant_id,
            audio_session_id=session.audio_session_id,
            sequence=event.sequence,
            start_ms=event.start_ms,
            end_ms=event.end_ms,
            text=event.text,
            words=event.words,
            status=status,
        )
        await self._persist(session, pending)
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

    async def _persist(self, session: ParticipantSession, segment: _PendingSegment) -> None:
        """Write a segment, or hold it until the database comes back.

        Tech spec 14.1. The transcript is still broadcast either way — the
        client should see what was said — and every held segment is retried
        ahead of the next one, so recovery needs no separate sweep.
        """
        self._pending.append(segment)
        async with self._persist_lock:
            batch = list(self._pending)
            try:
                async with session_scope() as db:
                    repo = SegmentRepository(db, self.meeting.organization_id)
                    for held in batch:
                        await repo.add_final(
                            meeting_id=self.meeting.meeting_id,
                            participant_id=held.participant_id,
                            audio_session_id=held.audio_session_id,
                            sequence=held.sequence,
                            start_ms=held.start_ms,
                            end_ms=held.end_ms,
                            text=held.text,
                            words=held.words,
                            status=held.status,
                            segment_id=held.segment_id,
                        )
            except Exception as exc:
                log.error(
                    "segment_persist_failed",
                    error_type=type(exc).__name__,
                    held=len(self._pending),
                )
                if len(self._pending) >= PERSISTENCE_BUFFER_MAX:
                    # Past here the runtime is holding more than it promised
                    # to. Say so rather than let the buffer grow without bound.
                    del self._pending[:-PERSISTENCE_BUFFER_MAX]
                    await self._publish_status(segment.participant_id, "unavailable")
            else:
                # Drop exactly what was written. Anything another pump appended
                # while this one was awaiting stays, and goes out next time.
                written = {held.segment_id for held in batch}
                self._pending = [p for p in self._pending if p.segment_id not in written]
                log.info("segments_persisted", count=len(batch))

    # ---- finalization ----------------------------------------------------

    async def drain(self, deadline_s: float = DRAIN_DEADLINE_S) -> None:
        """Tech spec 11 step 3: drain, flush, close open segments.

        `flush()` is the D-05 accelerated catch-up rather than a wait, which is
        what keeps this deadline generous instead of tight.
        """
        if self._idle_sweep is not None:
            self._idle_sweep.cancel()
        for task in self._grace.values():
            task.cancel()
        self._grace.clear()

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

        # Slice 4: the only place the decomposition is reported. There is no
        # metrics endpoint until Slice 6, so it is logged as one structured
        # record per meeting — which is also what the smoke test reads.
        METRICS.merge_latency(self.latency)
        log.info(
            "latency_decomposition",
            meeting_id=self.meeting.meeting_id,
            asr_version=self._asr_version,
            stages_ms=self.latency.snapshot(),
        )

    async def _close_participant(self, participant_id: str) -> None:
        """The transport went away. That is not the same as leaving.

        Tech spec 7.4 gives the client `RECONNECT_GRACE_S` to come back, so the
        stream is held open and the panel says "reconnecting". Only when the
        grace expires is the segment finalized and the participant announced as
        gone.
        """
        if participant_id in self._grace:
            return
        session = self._sessions.get(participant_id)
        if session is None:
            # Their stream was already closed — an idle close, most likely — so
            # there is nothing to hold open and no reason to wait. Without this
            # they would sit in the panel forever, present and silent.
            await self._announce_departure(participant_id)
            return
        session.disconnected()
        await self._set_speaking(participant_id, False)
        display_name = self._roster.get(participant_id)
        if display_name is not None:
            await self._broadcaster.publish(
                self.meeting.meeting_id,
                ParticipantEvent(
                    type="participant.reconnecting",
                    participant_id=participant_id,
                    display_name=display_name,
                ).model_dump(),
            )
        self._grace[participant_id] = asyncio.create_task(self._expire_grace(participant_id))

    async def _expire_grace(self, participant_id: str) -> None:
        """The client did not come back. Finalize the stream for good."""
        try:
            await asyncio.sleep(RECONNECT_GRACE_S)
        except asyncio.CancelledError:
            return
        self._grace.pop(participant_id, None)
        session = self._sessions.pop(participant_id, None)
        if session is None:
            return

        await session.stop()
        pump = self._pumps.pop(participant_id, None)
        if pump is not None:
            await asyncio.wait({pump}, timeout=5.0)
        await self._finalize_session(session)

        await self._announce_departure(participant_id)
        log.info("participant_stream_expired", participant_id=participant_id)

    async def _announce_departure(self, participant_id: str) -> None:
        display_name = self._roster.pop(participant_id, None)
        if display_name is None:
            return
        await self._set_speaking(participant_id, False)
        await self._broadcaster.publish(
            self.meeting.meeting_id,
            ParticipantEvent(
                type="participant.left",
                participant_id=participant_id,
                display_name=display_name,
            ).model_dump(),
        )

    async def _finalize_session(self, session: ParticipantSession) -> None:
        """Close one stream's ASR session, open segment, audio file and row."""
        try:
            await asyncio.wait_for(session.asr_session.flush(), timeout=5.0)
            await self._emit(session, session.segmenter.close_open())
            await session.asr_session.close()
        except TimeoutError:
            log.warning("finalize_drain_timeout", participant_id=session.participant_id)

        async with session_scope() as db:
            await AudioSessionRepository(db, self.meeting.organization_id).finish(
                session.audio_session_id,
                frames_received=session.frames_received,
                frames_dropped=session.frames_dropped,
            )
        handle = self._files.pop(session.participant_id, None)
        if handle is not None:
            handle.close()

    async def stop(self) -> None:
        if self._idle_sweep is not None:
            self._idle_sweep.cancel()
        for task in self._grace.values():
            task.cancel()
        self._grace.clear()
        for pump in self._pumps.values():
            pump.cancel()
        if self._consumer is not None:
            self._consumer.cancel()
        await self._ingress.stop()
        for handle in self._files.values():
            handle.close()
        self._files.clear()

        # Slice 4: the only place the decomposition is reported. There is no
        # metrics endpoint until Slice 6, so it is logged as one structured
        # record per meeting — which is also what the smoke test reads.
        METRICS.merge_latency(self.latency)
        log.info(
            "latency_decomposition",
            meeting_id=self.meeting.meeting_id,
            asr_version=self._asr_version,
            stages_ms=self.latency.snapshot(),
        )
