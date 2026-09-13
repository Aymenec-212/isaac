"""R4 identity and authorization through PostgreSQL and the actual gateway."""

import asyncio

import pytest
from sqlalchemy import select

from mosaique.app.auth.tokens import issue_host_token
from mosaique.domain.ids import new_id
from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import AudioSession, Participant, User
from mosaique.realtime.protocol.frames import encode_frame
from tests.conftest import host_token_for
from tests.integration.test_meeting_flow import PCM, auth, create_and_join
from tests.realtime.test_reconnect import stream

pytestmark = pytest.mark.integration


async def room(client, settings, tenant):
    token = host_token_for(settings, tenant)
    result = await client.post("/meetings", headers=auth(token), json={"title": "Identité"})
    body = result.json()
    return token, body["meeting"]["id"], body["invite_url"].split("t=")[1]


async def test_concurrent_join_retries_reuse_one_participant_and_keep_original_name(
    client, settings, tenants
):
    _, mid, invite = await room(client, settings, tenants["alpha"])
    body = {"display_name": "Amina", "invite_token": invite, "join_nonce": "a" * 32}
    responses = await asyncio.gather(
        *(client.post(f"/meetings/{mid}/join", json=body) for _ in range(5))
    )
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["participant"]["id"] for r in responses}) == 1
    retry = await client.post(f"/meetings/{mid}/join", json={**body, "display_name": "Changed"})
    assert retry.json()["participant"]["display_name"] == "Amina"
    async with session_scope() as db:
        people = (
            (await db.execute(select(Participant).where(Participant.meeting_id == mid)))
            .scalars()
            .all()
        )
        assert len(people) == 1 and people[0].join_nonce_hash != body["join_nonce"]


async def test_nonce_does_not_authenticate_and_is_scoped_to_meeting(client, settings, tenants):
    _, mid, invite = await room(client, settings, tenants["alpha"])
    _, other, other_invite = await room(client, settings, tenants["alpha"])
    body = {"display_name": "A", "invite_token": invite, "join_nonce": "b" * 32}
    first = await client.post(f"/meetings/{mid}/join", json=body)
    refused = await client.post(f"/meetings/{mid}/join", json={**body, "invite_token": "wrong"})
    assert refused.status_code == 401
    second = await client.post(
        f"/meetings/{other}/join", json={**body, "invite_token": other_invite}
    )
    assert first.json()["participant"]["id"] != second.json()["participant"]["id"]
    token = first.json()["session_token"]
    for suffix in ["", "/transcript", "/outputs"]:
        assert (
            await client.get(f"/meetings/{other}{suffix}", headers=auth(token))
        ).status_code == 403


async def test_guest_reads_own_meeting_but_cannot_list_create_or_mutate(client, settings, tenants):
    _, mid, joined = await create_and_join(client, settings, tenants["alpha"])
    headers = auth(joined["session_token"])
    detail = await client.get(f"/meetings/{mid}", headers=headers)
    assert detail.status_code == 200 and not detail.json()["can_manage"]
    assert len(detail.json()["participants"]) == 1
    assert (await client.get(f"/meetings/{mid}/transcript", headers=headers)).status_code == 200
    assert (await client.get(f"/meetings/{mid}/outputs", headers=headers)).status_code == 202
    assert (await client.get("/meetings", headers=headers)).status_code == 403
    assert (
        await client.post("/meetings", headers=headers, json={"title": "forbidden"})
    ).status_code == 403
    assert (await client.post(f"/meetings/{mid}/end", headers=headers)).status_code == 403
    assert (
        await client.post(f"/meetings/{mid}/outputs/regenerate", headers=headers)
    ).status_code == 403
    assert (
        await client.patch(
            f"/meetings/{mid}/segments/{new_id()}", headers=headers, json={"text": "forbidden"}
        )
    ).status_code == 403


async def test_only_owning_host_gets_manage_context(client, settings, tenants):
    token, mid, invite = await room(client, settings, tenants["alpha"])
    async with session_scope() as db:
        other = User(
            id=new_id(),
            organization_id=tenants["alpha"]["org_id"],
            email="other@alpha.test",
            display_name="Other",
        )
        db.add(other)
        other_id = other.id
    other_token = issue_host_token(
        user_id=other_id,
        organization_id=tenants["alpha"]["org_id"],
        secret=settings.token_secret,
        ttl_hours=1,
    )
    assert (await client.get(f"/meetings/{mid}", headers=auth(token))).json()["can_manage"]
    assert not (await client.get(f"/meetings/{mid}", headers=auth(other_token))).json()[
        "can_manage"
    ]
    assert (await client.post(f"/meetings/{mid}/end", headers=auth(other_token))).status_code == 403
    for principal, expected in [
        (token, True),
        (other_token, False),
        (host_token_for(settings, tenants["beta"]), False),
    ]:
        joined = await client.post(
            f"/meetings/{mid}/join",
            headers=auth(principal),
            json={"display_name": "H", "invite_token": invite, "join_nonce": new_id()},
        )
        assert joined.status_code == 200
        assert joined.json()["can_manage"] is expected


async def hello_capture(ws, joined, capture):
    await ws.send_json(
        {"type": "hello", "v": 1, "session_token": joined["session_token"], "capture_id": capture}
    )
    while True:
        message = await ws.receive_json()
        if message["type"] == "hello.ok":
            return message


async def test_same_capture_resumes_but_reload_opens_fresh_audio_session(
    ws_client, settings, tenants
):
    token, mid, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    pid = joined["participant"]["id"]
    async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as first:
        assert not (await hello_capture(first, joined, "capture-a"))["resume"]
        await stream(first, start=0, count=20)
        runtime = ws_client.registry.get(mid)
        original = runtime._sessions[pid].audio_session_id
    async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as resumed:
        assert (await hello_capture(resumed, joined, "capture-a"))["resume"]
        await stream(resumed, start=20, count=10)
        assert runtime._sessions[pid].audio_session_id == original
    async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as reloaded:
        assert not (await hello_capture(reloaded, joined, "capture-b"))["resume"]
        await stream(reloaded, start=0, count=10)
        assert runtime._sessions[pid].audio_session_id != original
        assert runtime._sessions[pid].frames_received == 10
        assert runtime.resume_info(pid, "capture-b").last_sequence == 9
        result = await ws_client.http.post(f"/meetings/{mid}/end", headers=auth(token))
        assert result.status_code == 200
    async with session_scope() as db:
        rows = (
            (await db.execute(select(AudioSession).where(AudioSession.meeting_id == mid)))
            .scalars()
            .all()
        )
        assert len(rows) == 2 and all(r.ended_at is not None for r in rows)
        assert (
            len(
                (await db.execute(select(Participant).where(Participant.meeting_id == mid)))
                .scalars()
                .all()
            )
            == 1
        )


async def test_obsolete_socket_cannot_remove_successor_or_submit_audio(
    ws_client, settings, tenants
):
    _, mid, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    pid = joined["participant"]["id"]
    async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as old:
        await hello_capture(old, joined, "old")
        await stream(old, start=0, count=10)
        async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as new:
            await hello_capture(new, joined, "new")
            await stream(new, start=0, count=5)
            await old.send_bytes(encode_frame(1000, 0, PCM))
            await asyncio.sleep(0.03)
            await stream(new, start=5, count=5)
            runtime = ws_client.registry.get(mid)
            assert runtime._sessions[pid].frames_received == 10
            assert runtime._sessions[pid].connected
            assert pid not in runtime._grace
            assert pid in ws_client.registry.broadcaster._sockets[mid]
