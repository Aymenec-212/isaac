"""R5's authenticated ICE and signaling contracts over the real ASGI gateway."""

import asyncio
import base64
import hashlib
import hmac

import pytest

from tests.conftest import host_token_for
from tests.integration.test_meeting_flow import auth
from tests.realtime.test_reconnect import hello as legacy_hello


async def receive_type(ws, kind):
    async with asyncio.timeout(2):
        while True:
            message = await ws.receive_json()
            if message.get("type") == kind:
                return message


async def hello(ws, token):
    await ws.send_json(
        {
            "v": 1,
            "type": "hello",
            "session_token": token,
            "capture_id": "capture",
            "client": {"voice": True},
        }
    )
    return await receive_type(ws, "hello.ok")


pytestmark = pytest.mark.integration


async def test_ice_config_mints_short_lived_turn_credentials_for_an_authorized_guest(
    ws_client, settings, tenants
):
    client = ws_client.http
    host = host_token_for(settings, tenants["alpha"])
    created = await client.post("/meetings", headers=auth(host), json={"title": "Voix"})
    meeting_id = created.json()["meeting"]["id"]
    invite = created.json()["invite_url"].split("t=")[1]
    joined = await client.post(
        f"/meetings/{meeting_id}/join",
        json={"display_name": "Guest", "invite_token": invite, "join_nonce": "c" * 32},
    )

    original = (
        settings.webrtc_stun_urls,
        settings.webrtc_turn_urls,
        settings.webrtc_turn_shared_secret,
    )
    settings.webrtc_stun_urls = ["stun:stun.example:3478"]
    settings.webrtc_turn_urls = ["turn:turn.example:3478?transport=udp"]
    settings.webrtc_turn_shared_secret = "turn-secret"
    try:
        url = f"/meetings/{meeting_id}/ice-config"
        assert (await client.get(url, headers=auth(host))).status_code == 403
        assert (
            await client.get(url, headers=auth(joined.json()["session_token"]))
        ).status_code != 200
        async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
            await legacy_hello(ws, joined.json()["session_token"])
            response = await client.get(url, headers=auth(joined.json()["session_token"]))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["ice_servers"][0] == {"urls": ["stun:stun.example:3478"]}
        turn = body["ice_servers"][1]
        assert turn["urls"] == settings.webrtc_turn_urls
        assert turn["username"].split(":", 1)[0].isdigit()
        expected = hmac.new(
            settings.webrtc_turn_shared_secret.encode(),
            turn["username"].encode(),
            hashlib.sha1,
        ).digest()
        assert base64.b64decode(turn["credential"]) == expected
    finally:
        (
            settings.webrtc_stun_urls,
            settings.webrtc_turn_urls,
            settings.webrtc_turn_shared_secret,
        ) = original


async def test_signaling_is_forwarded_only_to_the_authenticated_target(
    ws_client, settings, tenants
):
    host = host_token_for(settings, tenants["alpha"])
    created = await ws_client.http.post("/meetings", headers=auth(host), json={"title": "Signal"})
    other_id = created.json()["meeting"]["id"]
    other_invite = created.json()["invite_url"].split("t=")[1]
    first = (
        await ws_client.http.post(
            f"/meetings/{other_id}/join",
            json={"display_name": "A", "invite_token": other_invite, "join_nonce": "d" * 32},
        )
    ).json()
    second = (
        await ws_client.http.post(
            f"/meetings/{other_id}/join",
            json={"display_name": "B", "invite_token": other_invite, "join_nonce": "e" * 32},
        )
    ).json()

    async with ws_client.websocket_connect(f"/ws/meetings/{other_id}") as first_ws:
        first_hello = await hello(first_ws, first["session_token"])
        async with ws_client.websocket_connect(f"/ws/meetings/{other_id}") as second_ws:
            second_hello = await hello(second_ws, second["session_token"])
            peers = await receive_type(second_ws, "rtc.peers")
            assert len(peers["peers"]) == 2
            await first_ws.send_json(
                {
                    "v": 1,
                    "type": "rtc.offer",
                    "target_participant_id": second["participant"]["id"],
                    "sdp": "v=0",
                    "connection_id": first_hello["connection_id"],
                    "target_connection_id": second_hello["connection_id"],
                    "negotiation_id": "negotiation",
                }
            )
            forwarded = await asyncio.wait_for(second_ws.receive_json(), 1)
            while forwarded.get("type") != "rtc.offer":
                forwarded = await asyncio.wait_for(second_ws.receive_json(), 1)
            assert forwarded == {
                "v": 1,
                "type": "rtc.offer",
                "from_participant_id": first["participant"]["id"],
                "sdp": "v=0",
                "connection_id": first_hello["connection_id"],
                "target_connection_id": second_hello["connection_id"],
                "negotiation_id": "negotiation",
            }
            await first_ws.send_json(
                {
                    "v": 1,
                    "type": "rtc.offer",
                    "sdp": "v=0",
                    "target_participant_id": second["participant"]["id"],
                    "connection_id": first_hello["connection_id"],
                    "target_connection_id": "stale",
                    "negotiation_id": "n",
                }
            )
            assert (await receive_type(first_ws, "error"))["code"] == "SIGNAL_TARGET_UNAVAILABLE"


async def test_end_flush_is_sequence_bound_seals_audio_and_shares_request(
    ws_client, settings, tenants
):
    from mosaique.realtime.protocol.frames import encode_frame
    from tests.integration.test_meeting_flow import create_and_join

    host, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await ws.send_bytes(encode_frame(0, 0, b"\x00\x01" * 1920))
        first = asyncio.create_task(
            ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(host))
        )
        request = await receive_type(ws, "meeting.end_requested")
        second = asyncio.create_task(
            ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(host))
        )
        await ws.send_json(
            {"type": "audio.flush", "last_sequence": 1, "request_id": request["request_id"]}
        )
        assert (await receive_type(ws, "error"))["code"] == "AUDIO_FLUSH_INVALID"
        await ws.send_json(
            {"type": "audio.flush", "last_sequence": 0, "request_id": request["request_id"]}
        )
        ack = await receive_type(ws, "audio.flush.ok")
        assert ack["request_id"] == request["request_id"] and ack["last_sequence"] == 0
        await ws.send_bytes(encode_frame(1, 80, b"\x00\x01" * 1920))
        assert (await receive_type(ws, "error"))["code"] == "AUDIO_SEALED"
        results = await asyncio.gather(first, second)
        assert [r.status_code for r in results] == [200, 200]
