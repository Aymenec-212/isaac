"""Reconnect behaviour (tech spec 7.4, failure matrix rows 3 and 7).

A dropped socket is not a departure. The stream, its ASR session and its open
segment are held for `RECONNECT_GRACE_S`, so a client that comes back inside
the window continues mid-sentence instead of starting a new AudioSession.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import AudioSession
from mosaique.realtime.protocol.frames import encode_frame
from mosaique.realtime.sessions import meeting as meeting_module
from tests.integration.test_meeting_flow import create_and_join

pytestmark = pytest.mark.integration

PCM = b"\x00\x01" * 1920


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def hello(ws, token: str) -> dict:
    await ws.send_json({"v": 1, "type": "hello", "session_token": token})
    while True:
        message = await ws.receive_json()
        if message["type"] == "hello.ok":
            return message


async def stream(ws, *, start: int, count: int, settle: float = 0.15) -> int:
    """Send `count` frames starting at `seq`, returning the next free seq."""
    for offset in range(count):
        await ws.send_bytes(encode_frame(start + offset, (start + offset) * 80, PCM))
    await asyncio.sleep(settle)
    return start + count


async def test_a_dropped_socket_resumes_in_place_within_the_grace(ws_client, settings, tenants):
    """The whole point of the grace: one stream, not two."""
    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    token = joined["session_token"]
    participant_id = joined["participant"]["id"]

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        first = await hello(ws, token)
        assert first["resume"] is False
        next_seq = await stream(ws, start=0, count=60)

    # The socket is gone but the stream is not: the runtime holds it open.
    await asyncio.sleep(0.1)
    runtime = ws_client.registry.get(meeting_id)
    assert runtime is not None
    assert runtime.resume_info(participant_id).resuming is True
    assert runtime.resume_info(participant_id).last_sequence == next_seq - 1

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        again = await hello(ws, token)
        assert again["resume"] is True, "a hello inside the grace must resume"
        await stream(ws, start=next_seq, count=60)

    # One AudioSession, because the reconnect continued the stream rather than
    # opening a new one.
    async with session_scope() as db:
        rows = (
            (await db.execute(select(AudioSession).where(AudioSession.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1, f"reconnect created {len(rows)} audio sessions, expected 1"


async def test_a_replayed_client_buffer_does_not_duplicate_frames(ws_client, settings, tenants):
    """X-13: the sequence check survives the reconnect, so a replay is a no-op."""
    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    token = joined["session_token"]
    participant_id = joined["participant"]["id"]

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, token)
        next_seq = await stream(ws, start=0, count=40)

    await asyncio.sleep(0.1)
    runtime = ws_client.registry.get(meeting_id)
    assert runtime is not None
    before = runtime.resume_info(participant_id).last_sequence

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        assert (await hello(ws, token))["resume"] is True
        # The client replays its 15 s buffer: every one of these is a duplicate.
        await stream(ws, start=max(0, next_seq - 20), count=20)

    after = runtime.resume_info(participant_id).last_sequence
    assert after == before, "a replayed buffer advanced the sequence"


async def test_beyond_the_grace_the_stream_is_finalized_and_a_new_one_begins(
    ws_client, settings, tenants, monkeypatch
):
    """Tech spec 7.4: past the window, a reconnect is a new AudioSession."""
    monkeypatch.setattr(meeting_module, "RECONNECT_GRACE_S", 0.2)

    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    session_token = joined["session_token"]
    participant_id = joined["participant"]["id"]

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, session_token)
        await stream(ws, start=0, count=60)

    runtime = ws_client.registry.get(meeting_id)
    assert runtime is not None
    for _ in range(60):
        await asyncio.sleep(0.05)
        if not runtime.resume_info(participant_id).resuming:
            break
    assert runtime.resume_info(participant_id).resuming is False, "grace never expired"

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        late = await hello(ws, session_token)
        assert late["resume"] is False, "a hello after the grace must not resume"
        await stream(ws, start=0, count=40)

    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))
    async with session_scope() as db:
        rows = (
            (await db.execute(select(AudioSession).where(AudioSession.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
    assert len(rows) == 2, f"expected a second AudioSession after the grace, got {len(rows)}"


async def test_a_second_tab_closes_the_first_socket(ws_client, settings, tenants):
    """Failure matrix row 7: two tabs must not double one person's audio.

    Telling the first socket is not enough — a client that ignored the error
    would keep streaming — so the assertion here is that the socket is actually
    closed, not merely warned.
    """
    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    token = joined["session_token"]

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as first:
        await hello(first, token)
        await stream(first, start=0, count=20)

        async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as second:
            assert (await hello(second, token))["resume"] is True

            replaced = None
            with pytest.raises(ConnectionError):
                for _ in range(40):
                    message = await first.receive_json(timeout=1.0)
                    if message.get("code") == "SESSION_REPLACED":
                        replaced = message
            assert replaced is not None, "the first socket was never told"
            assert replaced["fatal"] is True
