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

    async def ensure(self, meeting: MeetingRef, started_at_ms: int) -> MeetingRuntime:
        async with self._lock:
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

    async def finalize(self, meeting_id: str) -> None:
        async with self._lock:
            runtime = self._runtimes.pop(meeting_id, None)
            self._ingresses.pop(meeting_id, None)
        if runtime is not None:
            await runtime.drain()
            await runtime.stop()

    async def shutdown(self) -> None:
        for meeting_id in list(self._runtimes):
            await self.finalize(meeting_id)
