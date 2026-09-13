"""R5's authenticated ICE and signaling contracts over the real ASGI gateway."""

import asyncio
import base64
import hashlib
import hmac

import pytest

from tests.conftest import host_token_for
from tests.integration.test_meeting_flow import auth
from tests.realtime.test_reconnect import hello

pytestmark = pytest.mark.integration


async def test_ice_config_mints_short_lived_turn_credentials_for_an_authorized_guest(
    client, settings, tenants
):
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
        response = await client.get(
            f"/meetings/{meeting_id}/ice-config", headers=auth(joined.json()["session_token"])
        )
        assert response.status_code == 200
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
    first = (await ws_client.http.post(
        f"/meetings/{other_id}/join",
        json={"display_name": "A", "invite_token": other_invite, "join_nonce": "d" * 32},
    )).json()
    second = (await ws_client.http.post(
        f"/meetings/{other_id}/join",
        json={"display_name": "B", "invite_token": other_invite, "join_nonce": "e" * 32},
    )).json()

    async with ws_client.websocket_connect(f"/ws/meetings/{other_id}") as first_ws:
        await hello(first_ws, first["session_token"])
        async with ws_client.websocket_connect(f"/ws/meetings/{other_id}") as second_ws:
            await hello(second_ws, second["session_token"])
            await first_ws.send_json(
                {
                    "v": 1,
                    "type": "rtc.offer",
                    "target_participant_id": second["participant"]["id"],
                    "sdp": "v=0",
                }
            )
            forwarded = await asyncio.wait_for(second_ws.receive_json(), 1)
            while forwarded.get("type") != "rtc.offer":
                forwarded = await asyncio.wait_for(second_ws.receive_json(), 1)
            assert forwarded == {
                "type": "rtc.offer",
                "from_participant_id": first["participant"]["id"],
                "sdp": "v=0",
            }
