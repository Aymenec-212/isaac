"""Deploying during a meeting (failure matrix, last row).

Level 1 accepts that a deploy interrupts a live meeting. What it does not
accept is losing the transcript, or leaving clients guessing: joins stop, open
segments are finalized, and sockets close with 1012 — "service restart" — which
clients treat as a reconnect rather than a fatal error.
"""

from __future__ import annotations

import pytest

from mosaique.realtime import runtime_state
from tests.integration.test_meeting_flow import create_and_join
from tests.realtime.test_reconnect import hello, stream

pytestmark = pytest.mark.integration


async def test_a_draining_server_refuses_new_sockets(ws_client, settings, tenants, monkeypatch):
    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    monkeypatch.setattr(runtime_state, "_draining", True)

    with pytest.raises(ConnectionError):
        async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
            await hello(ws, joined["session_token"])


async def test_shutdown_closes_live_sockets_and_finalizes_the_meeting(ws_client, settings, tenants):
    """The segments written before a restart are still there afterwards."""
    from sqlalchemy import select

    from mosaique.persistence.engine import session_scope
    from mosaique.persistence.models import TranscriptSegment

    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await stream(ws, start=0, count=120, settle=0.4)

        # A deploy lands mid-meeting.
        await ws_client.registry.close_sockets(code=1012)
        await ws_client.registry.shutdown()

    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        )
    assert rows, "a restart lost every segment"
    assert all(r.status in ("final", "gap") for r in rows)
