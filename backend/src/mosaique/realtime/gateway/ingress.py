"""`BrowserWebSocketIngress` — the one implementation of the D-04 seam.

This module is the *transport* side of the boundary. It knows about sockets and
frame bytes; the runtime on the other side knows about participants and audio.
Sockets push validated events in with `submit`; the runtime pulls them out with
`events()`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from mosaique.realtime.ingress import IngressEvent, MeetingRef


class BrowserWebSocketIngress:
    """Fans N per-participant sockets into one ordered event stream."""

    def __init__(self, maxsize: int = 2048) -> None:
        self._queue: asyncio.Queue[IngressEvent | None] = asyncio.Queue(maxsize=maxsize)
        self._meeting: MeetingRef | None = None
        self._stopped = False

    async def start(self, meeting: MeetingRef) -> None:
        self._meeting = meeting

    def submit(self, event: IngressEvent) -> bool:
        """Called from the socket handler. Never blocks the reader task."""
        if self._stopped:
            return False
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            return False
        return True

    async def events(self) -> AsyncIterator[IngressEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    async def stop(self) -> None:
        if not self._stopped:
            self._stopped = True
            await self._queue.put(None)
