"""Per-participant runtime state (tech spec 7.4, 8.4; ADR-11).

Owns three things and nothing else: the bounded audio queue, the ADR-11
timeline arithmetic, and the segmenter for this participant's stream.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mosaique.speech.interfaces import (
    FRAME_DURATION_MS,
    SILENCE_FRAME,
    ASRSession,
    AudioChunk,
)
from mosaique.transcript.segmenter import Segmenter

# Tech spec 8.4. Both values are [measure]; Slice 6 tunes them under real load.
QUEUE_LAGGING_FRAMES = 25  # ~2 s
QUEUE_MAX_FRAMES = 62  # ~5 s

# A seq gap wider than this is a genuine outage rather than a lost packet, and
# padding it would write minutes of silence. Slice 3 closes the AudioSession
# instead (blueprint D-02); Slice 1 simply caps the padding.
MAX_PADDING_FRAMES = 375  # 30 s


@dataclass
class QueuedFrame:
    seq: int
    pcm: bytes
    received_at_ms: int


class ParticipantSession:
    """One participant's audio stream for one AudioSession."""

    def __init__(
        self,
        *,
        participant_id: str,
        audio_session_id: str,
        asr_session: ASRSession,
        segmenter: Segmenter,
        epoch_ms: int,
    ) -> None:
        self.participant_id = participant_id
        self.audio_session_id = audio_session_id
        self.asr_session = asr_session
        self.segmenter = segmenter

        # ADR-11: this session's anchor on the meeting timeline, fixed at the
        # server receive time of its first accepted frame.
        self.epoch_ms = epoch_ms

        self._queue: asyncio.Queue[QueuedFrame | None] = asyncio.Queue(maxsize=QUEUE_MAX_FRAMES)
        self._last_seq: int | None = None
        # Transport state. The stream outlives its socket for the length of the
        # reconnect grace (tech spec 7.4), so "connected" is a property of this
        # session rather than of whether a socket object exists.
        self.connected = True
        self.frames_received = 0
        self.frames_missing = 0
        self.frames_dropped = 0
        self.frames_pushed = 0  # includes silence padding
        self.closed = False

    # ---- ADR-11 timeline -------------------------------------------------

    @property
    def stream_offset_ms(self) -> int:
        """Milliseconds of audio pushed into the recognizer, padding included.

        Derived from frame counts, never from a client clock, so it cannot
        drift and replays identically at any speed.
        """
        return self.frames_pushed * FRAME_DURATION_MS

    @property
    def meeting_time_ms(self) -> int:
        return self.epoch_ms + self.stream_offset_ms

    # ---- inbound ---------------------------------------------------------

    def accept(self, seq: int, pcm: bytes, received_at_ms: int) -> bool:
        """Enqueue a frame. Returns False when the queue is full.

        A duplicate or out-of-order `seq` is dropped here rather than deeper in
        the pipeline; a forward gap is allowed and padded on push, which keeps
        stream offset, audio-file offset, and capture time aligned.
        """
        if self._last_seq is not None and seq <= self._last_seq:
            return True  # duplicate: silently absorbed, counted by the gateway
        if self._last_seq is not None and seq > self._last_seq + 1:
            self.frames_missing += seq - self._last_seq - 1
        self._last_seq = seq
        self.frames_received += 1

        try:
            self._queue.put_nowait(QueuedFrame(seq=seq, pcm=pcm, received_at_ms=received_at_ms))
        except asyncio.QueueFull:
            # Slice 1 counts the loss. Slice 3 adds the visible `gap` segment
            # and the `stream.status` transitions that go with it.
            self.frames_dropped += 1
            return False
        return True

    @property
    def last_sequence(self) -> int:
        """The highest `seq` accepted so far; -1 before the first frame.

        The gateway seeds a resumed socket from this so a client replaying its
        buffer cannot smuggle duplicates past the check by reconnecting.
        """
        return -1 if self._last_seq is None else self._last_seq

    def disconnected(self) -> None:
        self.connected = False

    def reconnected(self) -> None:
        self.connected = True

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def lagging(self) -> bool:
        return self.queue_depth >= QUEUE_LAGGING_FRAMES

    async def next_frame(self) -> QueuedFrame | None:
        return await self._queue.get()

    async def stop(self) -> None:
        self.closed = True
        await self._queue.put(None)

    # ---- outbound to the recognizer --------------------------------------

    async def push(self, frame: QueuedFrame) -> int:
        """Push one frame, padding any gap with silence first.

        Padding is what makes `audio_file_byte_offset = session_ms * 48` exact,
        which is why FR-11 timestamp navigation needs no index table.
        Returns the number of padding frames inserted.
        """
        padding = 0
        expected = self.frames_pushed
        gap = frame.seq - expected
        if 0 < gap <= MAX_PADDING_FRAMES:
            for _ in range(gap):
                await self.asr_session.push_audio(
                    AudioChunk(pcm=SILENCE_FRAME, sequence=self.frames_pushed)
                )
                self.frames_pushed += 1
                padding += 1

        await self.asr_session.push_audio(AudioChunk(pcm=frame.pcm, sequence=self.frames_pushed))
        self.frames_pushed += 1
        return padding
