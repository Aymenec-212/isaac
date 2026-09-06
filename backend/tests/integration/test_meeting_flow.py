"""Slice 1 exit gate: the whole spine, on fakes.

Drives the real WebSocket gateway with real PCM frames, so this covers the
same path a browser takes: join -> frames -> recognizer -> segmenter ->
broadcast + persist -> end -> job -> outputs.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import AudioSession, Job, Meeting, TranscriptSegment
from mosaique.realtime.protocol.frames import encode_frame
from tests.conftest import host_token_for

pytestmark = pytest.mark.integration

PCM = b"\x00\x01" * 1920


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_and_join(client, settings, tenant, title="Réunion"):
    token = host_token_for(settings, tenant)
    created = await client.post("/meetings", json={"title": title}, headers=auth(token))
    body = created.json()
    meeting_id = body["meeting"]["id"]
    invite = body["invite_url"].split("t=")[1]
    joined = await client.post(
        f"/meetings/{meeting_id}/join",
        json={"display_name": "Amina", "invite_token": invite},
    )
    assert joined.status_code == 200
    return token, meeting_id, joined.json()


async def stream_until_finals(ws, *, frames: int, want: int = 2, batch: int = 10):
    """Send audio and collect transcript messages as they arrive."""
    received: list[dict] = []
    seq = 0
    for _ in range(frames // batch):
        for _ in range(batch):
            await ws.send_bytes(encode_frame(seq, seq * 80, PCM))
            seq += 1
        await asyncio.sleep(0.05)
        received.extend(ws.drain())
        if sum(1 for m in received if m["type"] == "transcript.segment.final") >= want:
            break
    await asyncio.sleep(0.1)
    received.extend(ws.drain())
    return received


async def test_join_returns_a_session_token_bound_to_the_meeting(client, settings, tenants):
    _, meeting_id, joined = await create_and_join(client, settings, tenants["alpha"])
    from mosaique.app.auth.tokens import verify_token

    principal = verify_token(joined["session_token"], secret=settings.token_secret)
    assert principal.kind == "participant"
    assert principal.meeting_id == meeting_id
    assert joined["ws_url"] == f"/ws/meetings/{meeting_id}"


async def test_join_with_a_wrong_invite_token_is_refused(client, settings, tenants):
    token = host_token_for(settings, tenants["alpha"])
    created = await client.post("/meetings", json={"title": "R"}, headers=auth(token))
    meeting_id = created.json()["meeting"]["id"]
    refused = await client.post(
        f"/meetings/{meeting_id}/join",
        json={"display_name": "Intrus", "invite_token": "wrong-token"},
    )
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "AUTH_INVALID_TOKEN"


async def test_websocket_refuses_audio_before_a_valid_hello(ws_client, settings, tenants):
    _, meeting_id, _ = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": "not-a-token"})
        message = await ws.receive_json()
    assert message["type"] == "error"
    assert message["code"] == "AUTH_INVALID_TOKEN"


async def test_speaking_produces_live_interim_then_final_segments(ws_client, settings, tenants):
    """The heart of Slice 1: audio in, attributed French transcript out."""
    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    participant_id = joined["participant"]["id"]

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        hello_ok = await ws.receive_json()
        assert hello_ok["type"] == "hello.ok"
        assert hello_ok["meeting_state"] == "LIVE"

        messages = await stream_until_finals(ws, frames=150, want=2)

    deltas = [m for m in messages if m["type"] == "transcript.delta"]
    finals = [m for m in messages if m["type"] == "transcript.segment.final"]

    assert deltas, "no interim transcript was broadcast"
    assert len(finals) >= 2, f"expected final segments, got {len(finals)}"
    assert all(m["participant_id"] == participant_id for m in deltas + finals)
    assert all(m["status"] == "interim" for m in deltas)
    assert all(m["status"] == "final" for m in finals)
    assert "Bonjour," in finals[0]["text"]

    # Revisions grow within a segment and interim text only ever extends.
    first_seq = deltas[0]["sequence"]
    same = [d for d in deltas if d["sequence"] == first_seq]
    assert [d["revision"] for d in same] == sorted(d["revision"] for d in same)
    for earlier, later in zip(same, same[1:], strict=False):
        assert later["text"].startswith(earlier["text"])


async def test_only_final_segments_reach_the_database(ws_client, settings, tenants):
    """ADR-05: interim state is memory-only and disposable."""
    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        await ws.receive_json()
        messages = await stream_until_finals(ws, frames=150, want=2)

    finals = [m for m in messages if m["type"] == "transcript.segment.final"]
    await asyncio.sleep(0.2)
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
    assert len(rows) >= len(finals) - 1
    assert all(r.status == "final" for r in rows)
    assert all(r.words for r in rows), "word timings should be stored for FR-11"

    transcript = await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    assert transcript.status_code == 200
    assert transcript.json()["segments"]


async def test_end_twice_yields_one_completed_meeting_and_one_job(ws_client, settings, tenants):
    """Tech spec success criterion 6."""
    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        await ws.receive_json()
        await stream_until_finals(ws, frames=120, want=1)

    first = await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))
    second = await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))
    assert first.status_code == second.status_code == 200
    assert first.json()["meeting"]["state"] == "COMPLETED"
    assert second.json()["meeting"]["state"] == "COMPLETED"

    async with session_scope() as db:
        meetings = (
            (await db.execute(select(Meeting).where(Meeting.id == meeting_id))).scalars().all()
        )
        jobs = (await db.execute(select(Job).where(Job.meeting_id == meeting_id))).scalars().all()
    assert len(meetings) == 1
    assert meetings[0].transcript_version == 1
    assert len(jobs) == 1, f"end twice must create one job, got {len(jobs)}"


async def test_a_guest_cannot_end_the_meeting(ws_client, settings, tenants):
    _, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    refused = await ws_client.http.post(
        f"/meetings/{meeting_id}/end",
        headers={"Authorization": f"Bearer {joined['session_token']}"},
    )
    assert refused.status_code == 403


async def test_finalization_writes_audio_session_counters(ws_client, settings, tenants):
    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        await ws.receive_json()
        await stream_until_finals(ws, frames=100, want=1)
    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

    async with session_scope() as db:
        audio_sessions = (
            (await db.execute(select(AudioSession).where(AudioSession.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
    assert len(audio_sessions) == 1
    assert audio_sessions[0].frames_received > 0
    assert audio_sessions[0].sample_rate == 24_000
