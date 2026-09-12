"""Real local WebSocket/MessagePack framing against a tiny peer, not real ASR."""

from __future__ import annotations

import pytest

from mosaique.asr_runtime.moshi_ws import MoshiWebSocketTransport
from mosaique.speech.adapters.kyutai.transport import TransportClosed

msgpack = pytest.importorskip("msgpack")
websockets = pytest.importorskip("websockets")


async def test_header_path_float32_and_close_on_real_local_socket():
    observed = {}

    async def peer(socket):
        observed["path"] = socket.request.path
        observed["key"] = socket.request.headers["kyutai-api-key"]
        await socket.send(msgpack.packb({"type": "Ready"}))
        raw = await socket.recv()
        observed["raw"] = raw
        observed["message"] = msgpack.unpackb(raw)
        await socket.send(msgpack.packb({"type": "Marker", "id": 7}))
        await socket.wait_closed()

    async with websockets.serve(peer, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        transport = MoshiWebSocketTransport(f"ws://127.0.0.1:{port}", api_key="test-key")
        try:
            await transport.connect()
            assert await transport.receive() == {"type": "Ready"}
            await transport.send({"type": "Audio", "pcm": [0.5]})
            assert await transport.receive() == {"type": "Marker", "id": 7}
        finally:
            await transport.close()
    assert observed["path"] == "/api/asr-streaming"
    assert observed["key"] == "test-key"
    assert observed["message"] == {"type": "Audio", "pcm": [0.5]}
    assert b"\xca\x3f\x00\x00\x00" in observed["raw"]  # f32, not f64 payload.


@pytest.mark.parametrize("payload", [b"\xc1", msgpack.packb(["not", "a", "map"]), "text"])
async def test_malformed_wire_message_is_transport_failure(payload):
    async def peer(socket):
        await socket.send(payload)
        await socket.wait_closed()

    async with websockets.serve(peer, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        transport = MoshiWebSocketTransport(f"ws://127.0.0.1:{port}")
        try:
            await transport.connect()
            with pytest.raises(TransportClosed):
                await transport.receive()
        finally:
            await transport.close()
