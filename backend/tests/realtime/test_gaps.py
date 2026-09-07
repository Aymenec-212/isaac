"""Missing audio becomes a visible marker, not an unexplained silence.

Tech spec 8.3: a run of frames that never arrived, longer than `GAP_MARKER_MS`,
is recorded as a `gap` segment. Failure matrix row 4.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import TranscriptSegment
from mosaique.realtime.protocol.frames import encode_frame
from tests.integration.test_meeting_flow import create_and_join
from tests.realtime.test_reconnect import auth, hello

pytestmark = pytest.mark.integration

PCM = b"\x00\x01" * 1920


async def send(ws, seqs) -> None:
    for seq in seqs:
        await ws.send_bytes(encode_frame(seq, seq * 80, PCM))
    await asyncio.sleep(0.2)


async def test_a_long_run_of_missing_frames_becomes_a_gap_segment(ws_client, settings, tenants):
    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await send(ws, range(0, 30))
        # 40 frames missing is 3.2 s, comfortably past the 2 s marker threshold.
        await send(ws, range(70, 110))
        messages = ws.drain()

    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

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

    gaps = [r for r in rows if r.status == "gap"]
    assert gaps, f"no gap segment was recorded; statuses were {[r.status for r in rows]}"
    assert gaps[0].text == ""
    # The marker covers the missing span, not a single instant.
    assert gaps[0].end_ms - gaps[0].start_ms >= 2_000

    broadcast = [m for m in messages if m["type"] == "transcript.segment.final"]
    assert any(m["text"] == "" for m in broadcast), "the gap was never broadcast"


async def test_a_short_run_of_missing_frames_is_padded_silently(ws_client, settings, tenants):
    """Below the threshold a dropped packet is padded, not announced.

    Marking every lost packet would make the transcript unreadable, which is
    why the spec sets a threshold rather than flagging any gap at all.
    """
    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await send(ws, range(0, 30))
        await send(ws, range(40, 90))  # 10 frames = 800 ms, under the threshold

    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

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
    assert [r for r in rows if r.status == "gap"] == []
