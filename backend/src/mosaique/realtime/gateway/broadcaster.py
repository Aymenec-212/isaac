"""Socket registry and the outbound half of the seam."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from mosaique.observability.logging import get_logger

log = get_logger(__name__)


class SocketLike(Protocol):
    async def send_json(self, data: Any) -> None: ...


class SocketBroadcaster:
    """Publishes runtime messages to every socket in a meeting."""

    def __init__(self) -> None:
        self._sockets: dict[str, dict[str, SocketLike]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self, meeting_id: str, participant_id: str, socket: SocketLike
    ) -> SocketLike | None:
        """Register a socket, returning any socket it replaced (tech spec 7.4)."""
        async with self._lock:
            room = self._sockets.setdefault(meeting_id, {})
            previous = room.get(participant_id)
            room[participant_id] = socket
            return previous

    async def unregister(self, meeting_id: str, participant_id: str) -> None:
        async with self._lock:
            room = self._sockets.get(meeting_id)
            if room is not None:
                room.pop(participant_id, None)
                if not room:
                    self._sockets.pop(meeting_id, None)

    async def publish(self, meeting_id: str, message: dict[str, object]) -> None:
        for participant_id, socket in list(self._sockets.get(meeting_id, {}).items()):
            try:
                await socket.send_json(message)
            except Exception:
                # A dead socket must never stall the transcript pipeline.
                log.info("broadcast_socket_dropped", participant_id=participant_id)

    async def send_to(self, participant_id: str, message: dict[str, object]) -> None:
        for room in self._sockets.values():
            socket = room.get(participant_id)
            if socket is not None:
                try:
                    await socket.send_json(message)
                except Exception:
                    log.info("send_socket_dropped", participant_id=participant_id)
                return
