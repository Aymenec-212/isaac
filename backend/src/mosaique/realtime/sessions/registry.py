"""Live meeting registry.

Process-local by design: it holds *transient* state only. The authoritative
record is PostgreSQL (skill 43), which is why a restart loses interim text but
never a final segment.
"""

from __future__ import annotations

import asyncio

from mosaique.realtime.gateway.broadcaster import SocketBroadcaster
from mosaique.realtime.gateway.ingress import BrowserWebSocketIngress
from mosaique.realtime.ingress import MeetingRef
from mosaique.realtime.sessions.meeting import MeetingRuntime
from mosaique.speech.audio import AudioStore
from mosaique.speech.interfaces import StreamingRecognizer


class MeetingRegistry:
    def __init__(
        self,
        *,
        recognizer: StreamingRecognizer,
        audio_store: AudioStore,
        broadcaster: SocketBroadcaster,
    ) -> None:
        self._recognizer = recognizer
        self._audio_store = audio_store
        self.broadcaster = broadcaster
        self._runtimes: dict[str, MeetingRuntime] = {}
        self._ingresses: dict[str, BrowserWebSocketIngress] = {}
        self._lock = asyncio.Lock()
        self._finalizing: dict[str, asyncio.Task[str | None]] = {}

    @property
    def recognizer(self) -> StreamingRecognizer:
        """The configured recognizer, for the `/readyz` probe.

        Exposed so health can ask the runtime whether it is ready *through the
        seam* rather than inferring it from configuration. Reading
        `settings.asr_runtime` would report what was requested, not what is
        actually loaded — and would hand the app-server knowledge of which
        adapter it holds, which is precisely what D-04 forbids.
        """
        return self._recognizer

    @property
    def audio_store(self) -> AudioStore:
        """Read access for the FR-11 audio route.

        The registry already owns the one configured store, and the review page
        has to read back exactly what the runtime wrote. Handing out the same
        object is what keeps `object_key` meaning the same thing on both sides;
        a second store built from settings could drift from this one.
        """
        return self._audio_store

    async def ensure(self, meeting: MeetingRef, started_at_ms: int) -> MeetingRuntime:
        async with self._lock:
            if meeting.meeting_id in self._finalizing:
                raise RuntimeError("meeting is finalizing")
            existing = self._runtimes.get(meeting.meeting_id)
            if existing is not None:
                return existing
            ingress = BrowserWebSocketIngress()
            runtime = MeetingRuntime(
                meeting=meeting,
                ingress=ingress,
                broadcaster=self.broadcaster,
                recognizer=self._recognizer,
                audio_store=self._audio_store,
                started_at_ms=started_at_ms,
            )
            await runtime.start()
            self._runtimes[meeting.meeting_id] = runtime
            self._ingresses[meeting.meeting_id] = ingress
            return runtime

    def ingress_for(self, meeting_id: str) -> BrowserWebSocketIngress | None:
        return self._ingresses.get(meeting_id)

    def get(self, meeting_id: str) -> MeetingRuntime | None:
        return self._runtimes.get(meeting_id)

    async def finalize(self, meeting_id: str) -> str | None:
        """Drain the runtime and report what produced its words.

        The `asr_version` comes back rather than being written here so it lands
        in the same transaction as `state=COMPLETED` and `transcript_version=1`
        (tech spec 11 step 6). None means no runtime existed — nobody ever
        connected — and the column is honestly left NULL.
        """
        async with self._lock:
            task = self._finalizing.get(meeting_id)
            if task is None:
                task = asyncio.create_task(self._finalize(meeting_id))
                self._finalizing[meeting_id] = task
        return await asyncio.shield(task)

    async def _finalize(self, meeting_id: str) -> str | None:
        runtime = self._runtimes.get(meeting_id)
        if runtime is None:
            return None
        try:
            await runtime.drain()
            return runtime.asr_version
        finally:
            self._runtimes.pop(meeting_id, None)
            self._ingresses.pop(meeting_id, None)

    async def close_sockets(self, *, code: int) -> None:
        """Hang up on everyone, with a code that says why (tech spec 14.1).

        1012 is "service restart", which is exactly what a deploy is. Clients
        reconnect on it rather than treating it as a fatal error, and the
        reconnect grace means they land back in their own segment.
        """
        await self.broadcaster.close_all(code=code)

    async def shutdown(self) -> None:
        for meeting_id in list(self._runtimes):
            await self.finalize(meeting_id)
