"""Socket registry and the outbound half of the seam."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Protocol

from mosaique.observability.logging import get_logger

log = get_logger(__name__)
WRITE_TIMEOUT_S = 1.0


class SocketLike(Protocol):
    async def send_json(self, data: Any) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


class SocketBroadcaster:
    """Publishes runtime messages to every socket in a meeting."""

    def __init__(self) -> None:
        self._sockets: dict[str, dict[str, SocketLike]] = {}
        self._lock = asyncio.Lock()
        # Failed sends remove delivery targets; ownership lasts until endpoint cleanup.
        self._owners: dict[str, dict[str, SocketLike]] = {}

    async def register(
        self, meeting_id: str, participant_id: str, socket: SocketLike
    ) -> SocketLike | None:
        """Register a socket, returning any socket it replaced (tech spec 7.4)."""
        async with self._lock:
            room = self._sockets.setdefault(meeting_id, {})
            owners = self._owners.setdefault(meeting_id, {})
            previous = owners.get(participant_id)
            owners[participant_id] = socket
            room[participant_id] = socket
            return previous

    def is_current(self, meeting_id: str, participant_id: str, socket: SocketLike) -> bool:
        return self._owners.get(meeting_id, {}).get(participant_id) is socket

    def is_connected(self, meeting_id: str, participant_id: str) -> bool:
        return participant_id in self._owners.get(meeting_id, {})

    def connected_participants(self, meeting_id: str) -> set[str]:
        return set(self._owners.get(meeting_id, {}))

    async def unregister(
        self, meeting_id: str, participant_id: str, socket: SocketLike | None = None
    ) -> bool:
        async with self._lock:
            owners = self._owners.get(meeting_id, {})
            if socket is not None and owners.get(participant_id) is not socket:
                return False
            removed = owners.pop(participant_id, None) is not None
            room = self._sockets.get(meeting_id, {})
            room.pop(participant_id, None)
            if not room:
                self._sockets.pop(meeting_id, None)
            if not owners:
                self._owners.pop(meeting_id, None)
            return removed

    async def publish(self, meeting_id: str, message: dict[str, object]) -> None:
        await asyncio.gather(
            *(
                self._send(meeting_id, participant_id, socket, message)
                for participant_id, socket in list(self._sockets.get(meeting_id, {}).items())
            )
        )

    async def _send(
        self, meeting_id: str, participant_id: str, socket: SocketLike, message: dict[str, object]
    ) -> None:
        try:
            await asyncio.wait_for(socket.send_json(message), WRITE_TIMEOUT_S)
        except Exception:
            async with self._lock:
                room = self._sockets.get(meeting_id, {})
                if room.get(participant_id) is socket:
                    room.pop(participant_id)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(socket.close(code=1013), WRITE_TIMEOUT_S)
            log.info("broadcast_socket_dropped", participant_id=participant_id)

    async def close_all(self, *, code: int) -> None:
        """Close every socket in every meeting, ignoring the ones already gone."""
        async with self._lock:
            rooms = [dict(room) for room in self._sockets.values()]
        for room in rooms:
            for participant_id, socket in room.items():
                try:
                    await asyncio.wait_for(socket.close(code=code), WRITE_TIMEOUT_S)
                except Exception:
                    log.info("close_socket_dropped", participant_id=participant_id)

    async def send_to(self, participant_id: str, message: dict[str, object]) -> None:
        for meeting_id, room in list(self._sockets.items()):
            socket = room.get(participant_id)
            if socket is not None:
                await self._send(meeting_id, participant_id, socket, message)
                return

    async def send_to_meeting(
        self, meeting_id: str, participant_id: str, message: dict[str, object]
    ) -> bool:
        """Deliver only to a currently connected participant in this meeting."""
        socket = self._sockets.get(meeting_id, {}).get(participant_id)
        if socket is None:
            return False
        await self._send(meeting_id, participant_id, socket, message)
        return self.is_connected(meeting_id, participant_id)
