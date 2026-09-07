"""The driver: N streams into the real gateway, one JSON report out.

It talks to a running app-server the way a browser does — HTTP to create and
join, then one WebSocket per participant carrying binary frames in the
tech spec 7.1 wire format. Nothing here imports the runtime, the registry, or
the segmenter. That is deliberate: a harness that reached inside could prove
things a browser cannot reproduce, which would make it useless as a debugging
tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from tools.replay.fixtures import iter_frames
from tools.replay.report import ParticipantRecord, ReplayReport, SegmentRecord
from tools.replay.scenario import ParticipantScript, Scenario
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from mosaique.realtime.protocol.frames import encode_frame
from mosaique.speech.interfaces import FRAME_DURATION_MS

# How long the harness waits for the transcript to go quiet after the last
# frame before it ends the meeting. Wall time on purpose: this is waiting for
# the server to catch up, not for stream time to pass.
DEFAULT_QUIET_MS = 750.0
DEFAULT_MAX_SETTLE_S = 30.0


def _now_ms() -> float:
    return time.time() * 1000.0


@dataclass
class _Stream:
    """One participant's live socket and the bookkeeping the report needs."""

    script: ParticipantScript
    participant_id: str
    session_token: str
    socket: ClientConnection
    audio: bytes
    frame_sent_at: list[float] = field(default_factory=list)
    messages: list[tuple[float, dict[str, Any]]] = field(default_factory=list)
    hello_ok_at: float = 0.0
    meeting_started_at: float = 0.0
    hydrated: list[tuple[str, int, str]] = field(default_factory=list)
    meeting_id: str = ""
    online: bool = True
    resumed: bool = False
    disconnects: int = 0
    duplicates_sent: int = 0
    reader: asyncio.Task[None] | None = None

    @property
    def last_ack(self) -> int | None:
        return len(self.frame_sent_at) - 1 if self.frame_sent_at else None

    def finals(self) -> dict[tuple[str, int], str]:
        return {
            (m["participant_id"], m["sequence"]): m["text"]
            for _, m in self.messages
            if m["type"] == "transcript.segment.final"
        }

    def roster(self) -> set[str]:
        """Who this socket was told about, live or replayed on join."""
        return {m["participant_id"] for _, m in self.messages if m["type"] == "participant.joined"}

    def speaking_transitions(self, participant_id: str) -> int:
        return sum(
            1
            for _, m in self.messages
            if m["type"] == "participant.speaking" and m["participant_id"] == participant_id
        )

    def view(self) -> dict[tuple[str, int], str]:
        """What this participant's browser ends up showing (tech spec 7.3)."""
        return {**{(p, s): t for p, s, t in self.hydrated}, **self.finals()}

    @property
    def display_name(self) -> str:
        return self.script.display_name

    @property
    def epoch_ms(self) -> float:
        """This stream's ADR-11 anchor, as closely as a client can observe it.

        The server fixes `epoch_ms` when it opens the stream, a moment before
        it sends `hello.ok`; the difference is the one-way trip of that
        message. Good enough to attribute a segment back to the frame that
        carried it, and never used for anything the transcript depends on.
        """
        return self.hello_ok_at - self.meeting_started_at


class ReplayHarness:
    def __init__(
        self,
        *,
        base_url: str,
        host_token: str,
        scenario: Scenario,
        speed: float | None = None,
        quiet_ms: float = DEFAULT_QUIET_MS,
        max_settle_s: float = DEFAULT_MAX_SETTLE_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._host_token = host_token
        self._scenario = scenario
        self._speed = speed if speed is not None else scenario.speed
        if self._speed <= 0:
            raise ValueError("speed must be positive")
        self._quiet_ms = quiet_ms
        self._stack = contextlib.AsyncExitStack()
        # Every reader task ever started, including the ones a reconnect
        # creates, so teardown can cancel all of them.
        self._readers: list[asyncio.Task[None]] = []
        self._max_settle_s = max_settle_s
        self._last_message_at = 0.0

    @property
    def _ws_base(self) -> str:
        return self._base_url.replace("https://", "wss://").replace("http://", "ws://")

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._host_token}"}

    async def run(self) -> ReplayReport:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as http:
            meeting_id, invite_token = await self._create_meeting(http)
            joins = [
                await self._join(http, meeting_id, invite_token, p)
                for p in self._scenario.participants
            ]

            async with contextlib.AsyncExitStack() as stack:
                self._stack = stack
                started = time.monotonic()
                try:
                    streams = await asyncio.gather(
                        *(
                            self._participate(stack, meeting_id, script, join)
                            for script, join in joins
                        )
                    )
                    await self._wait_for_quiet()
                    wall_seconds = time.monotonic() - started
                    await http.post(f"/meetings/{meeting_id}/end", headers=self._auth())
                    await self._wait_for_quiet()
                    for stream in streams:
                        await self._hydrate(http, meeting_id, stream)
                finally:
                    for reader in self._readers:
                        reader.cancel()
                    await asyncio.gather(*self._readers, return_exceptions=True)

        return self._build_report(meeting_id, list(streams), wall_seconds)

    async def _participate(
        self,
        stack: contextlib.AsyncExitStack,
        meeting_id: str,
        script: ParticipantScript,
        join: dict[str, Any],
    ) -> _Stream:
        """One participant's whole life: wait, connect, stream.

        The wait is wall time and is not divided by the speed factor; see
        `scenario` for why that is the only choice that survives a 10x replay.
        """
        # Build the audio before opening the socket. Generating it afterwards
        # holds an open, silent connection for as long as it takes, and the
        # server is right to hang up on a client that says nothing for 30 s
        # (tech spec 7.4).
        audio = script.audio(self._scenario.base_dir)
        if script.start_ms:
            await asyncio.sleep(script.start_ms / 1000.0)
        stream = await self._open_stream(stack, meeting_id, script, join, audio)
        self._watch(stream)
        await self._send(stream)
        return stream

    # ---- setup -----------------------------------------------------------

    async def _create_meeting(self, http: httpx.AsyncClient) -> tuple[str, str]:
        created = await http.post(
            "/meetings", json={"title": self._scenario.title}, headers=self._auth()
        )
        created.raise_for_status()
        body = created.json()
        return body["meeting"]["id"], body["invite_url"].split("t=")[1]

    async def _join(
        self,
        http: httpx.AsyncClient,
        meeting_id: str,
        invite_token: str,
        script: ParticipantScript,
    ) -> tuple[ParticipantScript, dict[str, Any]]:
        joined = await http.post(
            f"/meetings/{meeting_id}/join",
            json={"display_name": script.display_name, "invite_token": invite_token},
        )
        joined.raise_for_status()
        return script, joined.json()

    async def _open_stream(
        self,
        stack: contextlib.AsyncExitStack,
        meeting_id: str,
        script: ParticipantScript,
        join: dict[str, Any],
        audio: bytes,
    ) -> _Stream:
        socket = await stack.enter_async_context(
            connect(f"{self._ws_base}/ws/meetings/{meeting_id}", max_size=None)
        )
        await socket.send(json.dumps(self._hello(join["session_token"], None)))
        stream = _Stream(
            script=script,
            participant_id=join["participant"]["id"],
            session_token=join["session_token"],
            socket=socket,
            audio=audio,
            meeting_id=meeting_id,
        )
        # Roster messages for participants already in the room can beat
        # `hello.ok` onto the wire; keep them rather than dropping them.
        while True:
            try:
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
            except ConnectionClosed as exc:
                raise RuntimeError(
                    f"the server hung up during the opening handshake for "
                    f"{script.display_name} ({exc}); close code 1008 means it could not find "
                    f"the meeting or the participant"
                ) from exc
            stream.messages.append((_now_ms(), message))
            if message["type"] == "hello.ok":
                stream.hello_ok_at = _now_ms()
                stream.meeting_started_at = float(message["meeting_started_at"])
                return stream
            if message["type"] == "error" and message.get("fatal"):
                raise RuntimeError(f"handshake refused: {message['code']} {message['message']}")

    def _watch(self, stream: _Stream) -> None:
        """Start reading a stream's socket, and remember the task."""
        stream.reader = asyncio.create_task(self._read(stream))
        self._readers.append(stream.reader)

    @staticmethod
    def _hello(session_token: str, last_ack: int | None) -> dict[str, Any]:
        return {
            "v": 1,
            "type": "hello",
            "session_token": session_token,
            "last_ack_sequence": last_ack,
            "client": {"ua": "replay-harness", "sample_rate": 24000},
        }

    async def _hydrate(self, http: httpx.AsyncClient, meeting_id: str, stream: _Stream) -> None:
        """Fetch the transcript as this participant, the way their browser does.

        A late joiner never receives the finals broadcast before its socket
        existed, so "both browsers show the same thing" is a property of
        hydration plus broadcast, not of broadcast alone (tech spec 7.3).
        """
        response = await http.get(
            f"/meetings/{meeting_id}/transcript",
            headers={"Authorization": f"Bearer {stream.session_token}"},
        )
        response.raise_for_status()
        stream.hydrated = [
            (row["participant_id"], row["sequence"], row["text"])
            for row in response.json()["segments"]
        ]

    # ---- the replay itself ------------------------------------------------

    async def _read(self, stream: _Stream) -> None:
        async for raw in stream.socket:
            message = json.loads(raw)
            if message.get("type") == "ping":
                # The harness is a client and owes the server the same answer a
                # browser does (tech spec 7.4). Without this the server calls
                # the socket dead after 30 s of one-way traffic — which is
                # exactly what a long replay looks like once the audio stops.
                with contextlib.suppress(Exception):
                    await stream.socket.send(
                        json.dumps({"v": 1, "type": "pong", "t": message.get("t", 0)})
                    )
                continue
            # A keepalive is not transcript activity, so it must not keep
            # `_wait_for_quiet` awake for ever.
            self._last_message_at = _now_ms()
            stream.messages.append((self._last_message_at, message))

    async def _send(self, stream: _Stream) -> None:
        """Pace one stream at `speed` times real time, without drifting.

        Faults are injected by stream offset rather than wall time, so a
        disconnect lands at the same point in the transcript at 1x and at 10x
        — which is the only way an accelerated replay can reproduce one.
        """
        script = stream.script
        loop = asyncio.get_running_loop()
        origin = loop.time()
        interval = FRAME_DURATION_MS / 1000.0 / self._speed
        sent: list[tuple[int, bytes]] = []
        offline: list[tuple[int, bytes]] = []
        # Faults fire on the first frame at or past their offset rather than on
        # an exact match: frames land every 80 ms, and a scenario should not
        # have to know that to place a disconnect.
        dropped = False
        duplicated = False

        for sequence, payload in enumerate(iter_frames(stream.audio)):
            offset_ms = sequence * FRAME_DURATION_MS
            delay = (origin + sequence * interval) - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                # Behind schedule, which at high speed factors is every frame:
                # the deadline arithmetic then never awaits anything and this
                # loop starves the reader task on the same event loop. The
                # reader is what answers the server's pings, so without this
                # yield a long fast replay looks like a one-way socket and the
                # server correctly hangs up (tech spec 7.4). The same starving
                # bug bit the server's own frame pump in Slice 1.
                await asyncio.sleep(0)

            if (
                not dropped
                and script.disconnect_at_ms is not None
                and (offset_ms >= script.disconnect_at_ms)
            ):
                dropped = True
                await self._drop_and_return(stream, offline)
                origin = loop.time() - sequence * interval

            if (
                not duplicated
                and script.duplicate_at_ms is not None
                and (offset_ms >= script.duplicate_at_ms)
            ):
                duplicated = True
                # Replay recent frames exactly as a client emptying its buffer
                # would. The server must absorb them without duplicating text.
                for old_seq, old_pcm in sent[-script.duplicate_frames :]:
                    await stream.socket.send(
                        encode_frame(old_seq, old_seq * FRAME_DURATION_MS, old_pcm)
                    )
                stream.duplicates_sent += min(script.duplicate_frames, len(sent))

            sent.append((sequence, payload))
            if not stream.online:
                # Captured while offline: held, then replayed on reconnect, the
                # same 15 s buffer the browser client keeps.
                offline.append((sequence, payload))
                continue
            stream.frame_sent_at.append(_now_ms())
            await stream.socket.send(encode_frame(sequence, offset_ms, payload))

    async def _drop_and_return(self, stream: _Stream, offline: list[tuple[int, bytes]]) -> None:
        """Lose the socket, wait, come back, and replay what was captured."""
        stream.online = False
        stream.disconnects += 1
        with contextlib.suppress(Exception):
            await stream.socket.close()
        await asyncio.sleep(stream.script.reconnect_after_ms / 1000.0)

        socket = await self._stack.enter_async_context(
            connect(f"{self._ws_base}/ws/meetings/{stream.meeting_id}", max_size=None)
        )
        await socket.send(json.dumps(self._hello(stream.session_token, stream.last_ack)))
        while True:
            try:
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
            except ConnectionClosed as exc:
                raise RuntimeError(
                    f"the server hung up during the reconnect handshake for "
                    f"{stream.display_name} ({exc}); close code 1008 means it could not find "
                    f"the meeting or the participant"
                ) from exc
            stream.messages.append((_now_ms(), message))
            if message["type"] == "hello.ok":
                stream.resumed = bool(message.get("resume"))
                break
        stream.socket = socket
        self._watch(stream)
        stream.online = True

        for sequence, payload in offline:
            stream.frame_sent_at.append(_now_ms())
            await socket.send(encode_frame(sequence, sequence * FRAME_DURATION_MS, payload))
        offline.clear()

    async def _wait_for_quiet(self) -> None:
        """Wait until the transcript stops arriving, or give up."""
        self._last_message_at = _now_ms()
        deadline = time.monotonic() + self._max_settle_s
        while time.monotonic() < deadline:
            await asyncio.sleep(self._quiet_ms / 4000.0)
            if _now_ms() - self._last_message_at >= self._quiet_ms:
                return

    # ---- report -----------------------------------------------------------

    def _build_report(
        self, meeting_id: str, streams: list[_Stream], wall_seconds: float
    ) -> ReplayReport:
        by_id = {s.participant_id: s for s in streams}
        primary = streams[0]

        # Broadcast: every final published while a socket was connected must
        # have reached it. A late joiner legitimately misses what was said
        # before it arrived; hydration is what closes that gap.
        first_seen: dict[tuple[str, int], float] = {}
        for stream in streams:
            for at_ms, message in stream.messages:
                if message["type"] == "transcript.segment.final":
                    key = (message["participant_id"], message["sequence"])
                    first_seen[key] = min(first_seen.get(key, at_ms), at_ms)

        reached_every_socket = all(
            first_seen[key] < stream.hello_ok_at
            for stream in streams
            for key in first_seen.keys() - stream.finals().keys()
        )
        everyone = {stream.participant_id for stream in streams}
        roster_complete = all(stream.roster() >= everyone for stream in streams)
        views = [stream.view() for stream in streams]
        views_identical = all(view == views[0] for view in views)
        persisted = {(p, sequence) for p, sequence, _ in primary.hydrated}
        finals_all_persisted = all(
            key in persisted for stream in streams for key in stream.finals()
        )

        first_delta_at: dict[tuple[str, int], float] = {}
        deltas = 0
        for at_ms, message in primary.messages:
            if message["type"] != "transcript.delta":
                continue
            deltas += 1
            first_delta_at.setdefault((message["participant_id"], message["sequence"]), at_ms)

        segments: list[SegmentRecord] = []
        for at_ms, message in primary.messages:
            if message["type"] != "transcript.segment.final":
                continue
            owner = by_id.get(message["participant_id"])
            arrived = first_delta_at.get((message["participant_id"], message["sequence"]), at_ms)
            segments.append(
                SegmentRecord(
                    participant_id=message["participant_id"],
                    display_name=owner.display_name if owner else message["participant_id"],
                    sequence=message["sequence"],
                    segment_id=message["segment_id"],
                    text=message["text"],
                    start_ms=message["start_ms"],
                    end_ms=message["end_ms"],
                    duration_ms=message["end_ms"] - message["start_ms"],
                    first_word_latency_ms=round(
                        arrived - (primary.meeting_started_at + message["start_ms"]), 1
                    ),
                    pipeline_latency_ms=self._pipeline_latency(owner, message, arrived),
                )
            )

        stream_ms = max(len(s.frame_sent_at) for s in streams) * FRAME_DURATION_MS
        return ReplayReport(
            scenario=self._scenario.name,
            speed=self._speed,
            meeting_id=meeting_id,
            wall_seconds=wall_seconds,
            stream_seconds=stream_ms / 1000.0,
            participants=[
                ParticipantRecord(
                    participant_id=s.participant_id,
                    display_name=s.display_name,
                    start_ms=s.script.start_ms,
                    frames_sent=len(s.frame_sent_at),
                    speaking_transitions=primary.speaking_transitions(s.participant_id),
                    disconnects=s.disconnects,
                    duplicates_sent=s.duplicates_sent,
                    resumed=s.resumed,
                )
                for s in streams
            ],
            segments=segments,
            deltas=deltas,
            sockets=len(streams),
            broadcast_reached_every_socket=reached_every_socket,
            roster_complete=roster_complete,
            views_identical=views_identical,
            finals_all_persisted=finals_all_persisted,
        )

    def _pipeline_latency(
        self, owner: _Stream | None, message: dict[str, Any], arrived: float
    ) -> float | None:
        """Turnaround from the frame that carried the word to the text coming back."""
        if owner is None:
            return None
        index = int((message["start_ms"] - owner.epoch_ms) // FRAME_DURATION_MS)
        if not 0 <= index < len(owner.frame_sent_at):
            return None
        return round(arrived - owner.frame_sent_at[index], 1)
