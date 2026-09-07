"""Ping, pong, and hanging up on a socket that has gone quiet (tech spec 7.4).

Failure matrix row 3: a suspended tab usually does not close its connection, so
silence — not an error — is what says the client is gone.
"""

from __future__ import annotations

import pytest

from mosaique.realtime.gateway import endpoint as endpoint_module
from tests.integration.test_meeting_flow import create_and_join
from tests.realtime.test_reconnect import hello, stream

pytestmark = pytest.mark.integration


async def test_the_server_answers_a_client_ping(ws_client, settings, tenants):
    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await ws.send_json({"v": 1, "type": "ping", "t": 4242})
        for _ in range(20):
            message = await ws.receive_json(timeout=2.0)
            if message["type"] == "pong":
                assert message["t"] == 4242
                break
        else:
            raise AssertionError("no pong came back")


async def test_a_silent_socket_is_hung_up_on_and_starts_the_grace(
    ws_client, settings, tenants, monkeypatch
):
    """No pong and no frame for `STALE_AFTER_S` closes the socket.

    Closing is the point: it is what puts the stream into the reconnect grace,
    so a tab that comes back finds its segment still open rather than a new one.
    """
    monkeypatch.setattr(endpoint_module, "PING_INTERVAL_S", 0.05)
    monkeypatch.setattr(endpoint_module, "STALE_AFTER_S", 0.2)

    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    participant_id = joined["participant"]["id"]

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await stream(ws, start=0, count=10)
        # Now say nothing at all. The server should give up on us.
        with pytest.raises(ConnectionError):
            for _ in range(200):
                await ws.receive_json(timeout=2.0)

    runtime = ws_client.registry.get(meeting_id)
    assert runtime is not None
    assert runtime.resume_info(participant_id).resuming is True, (
        "hanging up on a stale socket must start the grace, not end the stream"
    )
