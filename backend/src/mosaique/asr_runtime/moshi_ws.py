"""WebSocket/MessagePack framing for the pinned remote ASR protocol.

R2 exercises this transport against a real localhost socket with a scripted peer.
That verifies framing/auth headers, not NVIDIA inference. Optional dependencies
remain lazy so fake/MLX development needs no remote-runtime packages.
"""

from __future__ import annotations

import contextlib
from typing import Any

from mosaique.speech.adapters.kyutai.transport import Message, TransportClosed

ASR_STREAMING_PATH = "/api/asr-streaming"
API_KEY_HEADER = "kyutai-api-key"


class MoshiWebSocketTransport:
    """One connection. Reconnecting is the backend's business, not this one's."""

    def __init__(self, base_url: str, *, api_key: str | None = None) -> None:
        self._url = base_url.rstrip("/") + ASR_STREAMING_PATH
        self._api_key = api_key
        self._socket: Any = None

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - optional extra
            raise TransportClosed(
                'moshi-server support needs the extra: uv pip install -e ".[moshi-server]"'
            ) from exc
        headers = {API_KEY_HEADER: self._api_key} if self._api_key else None
        try:
            self._socket = await websockets.connect(
                self._url,
                additional_headers=headers,
                open_timeout=5,
                close_timeout=1,
                max_size=1_048_576,
                max_queue=16,
            )
        except Exception as exc:
            raise TransportClosed("could not connect to ASR endpoint") from exc

    async def send(self, message: Message) -> None:
        import msgpack

        if self._socket is None:
            raise TransportClosed("send before connect")
        try:
            await self._socket.send(
                msgpack.packb(message, use_bin_type=True, use_single_float=True)
            )
        except Exception as exc:
            raise TransportClosed(str(exc)) from exc

    async def receive(self) -> Message:
        import msgpack

        if self._socket is None:
            raise TransportClosed("receive before connect")
        try:
            raw = await self._socket.recv()
        except Exception as exc:
            raise TransportClosed(str(exc)) from exc
        try:
            decoded = msgpack.unpackb(raw, raw=False)
        except (ValueError, TypeError, msgpack.exceptions.UnpackException) as exc:
            raise TransportClosed("invalid ASR MessagePack") from exc
        if not isinstance(decoded, dict):
            raise TransportClosed(f"expected a msgpack map, got {type(decoded).__name__}")
        return decoded

    async def close(self) -> None:
        if self._socket is not None:
            socket, self._socket = self._socket, None
            with contextlib.suppress(Exception):  # closing an already-dead socket
                await socket.close()
