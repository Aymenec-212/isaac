"""Muting, and what a long silence does to the AudioSession (blueprint D-02, R-1).

D-02 answers mute and network stall the same way: past `IDLE_CLOSE_S` the
AudioSession is closed rather than padded with minutes of zeroes, and the next
frame opens a new one with a fresh anchor. The participant never leaves.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import AudioSession, TranscriptSegment
from mosaique.realtime.sessions import meeting as meeting_module
from tests.integration.test_meeting_flow import create_and_join
from tests.realtime.test_reconnect import auth, hello, stream

pytestmark = pytest.mark.integration


async def test_a_long_silence_closes_the_audio_session_and_the_next_frame_opens_another(
    ws_client, settings, tenants, monkeypatch
):
    monkeypatch.setattr(meeting_module, "IDLE_CLOSE_S", 0.25)
    monkeypatch.setattr(meeting_module, "IDLE_SWEEP_S", 0.05)

    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    participant_id = joined["participant"]["id"]

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        next_seq = await stream(ws, start=0, count=60)

        runtime = ws_client.registry.get(meeting_id)
        assert runtime is not None
        first_audio_session = runtime._sessions[participant_id].audio_session_id

        # Go quiet for longer than the idle window.
        await asyncio.sleep(0.6)
        assert participant_id not in runtime._sessions, "idle stream was never closed"

        # Speaking again must work, on a new AudioSession.
        await stream(ws, start=next_seq, count=40)
        second = runtime._sessions[participant_id].audio_session_id
        assert second != first_audio_session

    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

    async with session_scope() as db:
        rows = (
            (await db.execute(select(AudioSession).where(AudioSession.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
        segments = (
            (
                await db.execute(
                    select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 2, f"expected two AudioSessions across the pause, got {len(rows)}"
    assert all(r.ended_at is not None for r in rows), "a closed AudioSession must be stamped"

    # Sequence numbering continues across the pause rather than restarting,
    # which is what keeps `(participant_id, sequence)` unique (tech spec 10).
    sequences = sorted(s.sequence for s in segments)
    assert len(sequences) == len(set(sequences)), f"sequence restarted: {sequences}"


async def test_pausing_is_recorded_and_a_frame_unpauses(ws_client, settings, tenants):
    """R-1: `audio.pause` is honoured rather than accepted and ignored."""
    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    participant_id = joined["participant"]["id"]

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await stream(ws, start=0, count=10)

        runtime = ws_client.registry.get(meeting_id)
        assert runtime is not None
        assert runtime._sessions[participant_id].paused is False

        await ws.send_json({"v": 1, "type": "audio.pause"})
        await asyncio.sleep(0.15)
        assert runtime._sessions[participant_id].paused is True

        await ws.send_json({"v": 1, "type": "audio.resume"})
        await asyncio.sleep(0.15)
        assert runtime._sessions[participant_id].paused is False


async def join_two(http, settings, tenant):
    """Create a meeting and join two participants, keeping the invite token."""
    from tests.conftest import host_token_for

    token = host_token_for(settings, tenant)
    created = await http.post("/meetings", json={"title": "Panne"}, headers=auth(token))
    body = created.json()
    meeting_id = body["meeting"]["id"]
    invite = body["invite_url"].split("t=")[1]
    people = []
    for name in ("Amina", "Témoin"):
        joined = await http.post(
            f"/meetings/{meeting_id}/join",
            json={"display_name": name, "invite_token": invite},
        )
        assert joined.status_code == 200
        people.append(joined.json())
    return token, meeting_id, people


async def test_someone_who_goes_idle_then_disconnects_still_leaves_the_panel(
    ws_client, settings, tenants, monkeypatch
):
    """An idle-closed stream has nothing to hold open, so the grace is skipped.

    Without this they would sit in the participant panel forever, present and
    silent, because the departure path used to give up when it found no stream.
    """
    monkeypatch.setattr(meeting_module, "IDLE_CLOSE_S", 0.2)
    monkeypatch.setattr(meeting_module, "IDLE_SWEEP_S", 0.05)

    _, meeting_id, (speaker, watcher_join) = await join_two(
        ws_client.http, settings, tenants["alpha"]
    )

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as watcher:
        await hello(watcher, watcher_join["session_token"])

        async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
            await hello(ws, speaker["session_token"])
            await stream(ws, start=0, count=30)
            await asyncio.sleep(0.5)  # long enough for the idle close

        await asyncio.sleep(0.3)
        events = [m for m in watcher.drain() if m["type"] == "participant.left"]

    assert any(m["participant_id"] == speaker["participant"]["id"] for m in events), (
        "the idle participant never left the roster"
    )
