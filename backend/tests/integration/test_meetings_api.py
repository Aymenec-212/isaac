"""Slice 0 exit gate: create a meeting, read it back, and prove tenancy fails closed."""

from __future__ import annotations

import pytest

from tests.conftest import host_token_for

pytestmark = pytest.mark.integration


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_livez_touches_no_dependency(client):
    r = await client.get("/livez")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_create_meeting_then_read_it_back(client, settings, tenants):
    token = host_token_for(settings, tenants["alpha"])

    created = await client.post("/meetings", json={"title": "Point hebdo"}, headers=auth(token))
    assert created.status_code == 201
    body = created.json()
    meeting_id = body["meeting"]["id"]

    assert body["meeting"]["state"] == "JOINABLE"
    assert body["meeting"]["language"] == "fr"
    assert body["meeting"]["source_kind"] == "direct"
    assert body["meeting"]["transcript_version"] is None
    assert body["host_token"]
    assert meeting_id in body["invite_url"]

    fetched = await client.get(f"/meetings/{meeting_id}", headers=auth(token))
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Point hebdo"


async def test_invite_token_is_not_returned_in_meeting_reads(client, settings, tenants):
    """The invite token appears once, in the create response. Never again."""
    token = host_token_for(settings, tenants["alpha"])
    created = await client.post("/meetings", json={"title": "Discret"}, headers=auth(token))
    meeting_id = created.json()["meeting"]["id"]

    fetched = await client.get(f"/meetings/{meeting_id}", headers=auth(token))
    assert "invite_token" not in fetched.text
    assert "invite_token_hash" not in fetched.text


async def test_meeting_appears_in_list_for_its_own_organization(client, settings, tenants):
    token = host_token_for(settings, tenants["alpha"])
    created = await client.post("/meetings", json={"title": "Retro"}, headers=auth(token))
    meeting_id = created.json()["meeting"]["id"]

    listed = await client.get("/meetings", headers=auth(token))
    assert listed.status_code == 200
    assert meeting_id in [m["id"] for m in listed.json()["meetings"]]


async def test_cross_tenant_read_fails_closed(client, settings, tenants):
    """Exit gate: org beta must not be able to read org alpha's meeting."""
    alpha_token = host_token_for(settings, tenants["alpha"])
    beta_token = host_token_for(settings, tenants["beta"])

    created = await client.post(
        "/meetings", json={"title": "Confidentiel"}, headers=auth(alpha_token)
    )
    meeting_id = created.json()["meeting"]["id"]

    denied = await client.get(f"/meetings/{meeting_id}", headers=auth(beta_token))
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "MEETING_NOT_FOUND"
    assert "Confidentiel" not in denied.text


async def test_cross_tenant_list_is_empty(client, settings, tenants):
    alpha_token = host_token_for(settings, tenants["alpha"])
    beta_token = host_token_for(settings, tenants["beta"])
    await client.post("/meetings", json={"title": "Alpha only"}, headers=auth(alpha_token))

    listed = await client.get("/meetings", headers=auth(beta_token))
    assert [m for m in listed.json()["meetings"] if m["title"] == "Alpha only"] == []


async def test_requests_without_a_token_are_rejected(client):
    r = await client.get("/meetings")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_INVALID_TOKEN"


async def test_malformed_meeting_id_is_not_found_not_a_crash(client, settings, tenants):
    token = host_token_for(settings, tenants["alpha"])
    r = await client.get("/meetings/not-a-ulid", headers=auth(token))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "MEETING_NOT_FOUND"


async def test_error_responses_carry_a_request_id(client):
    r = await client.get("/meetings", headers={"x-request-id": "req-abc"})
    assert r.json()["error"]["request_id"] == "req-abc"


async def test_transcript_search_filters_to_matching_segments(ws_client, settings, tenants):
    """FR-10 through the real route (tech spec §6 `?q=`)."""
    from tests.integration.test_meeting_flow import auth, create_and_join, stream_until_finals

    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        await ws.receive_json()
        await stream_until_finals(ws, frames=150, want=2)
    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

    whole = (
        await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    ).json()
    assert whole["segments"], "need a transcript to search"
    assert whole["query"] is None
    assert whole["total_segments"] == len(whole["segments"])

    # Take a word the fake actually said, so the assertion is about search
    # rather than about what the script happens to contain.
    word = whole["segments"][0]["text"].split()[0].strip(".,").lower()

    filtered = (
        await ws_client.http.get(
            f"/meetings/{meeting_id}/transcript", params={"q": word}, headers=auth(token)
        )
    ).json()

    assert filtered["query"] == word
    assert filtered["total_segments"] == whole["total_segments"], "the total is before filtering"
    assert 0 < len(filtered["segments"]) <= len(whole["segments"])
    assert all(word in s["text"].lower() for s in filtered["segments"])


async def test_search_returns_offsets_that_slice_the_segment_text(ws_client, settings, tenants):
    """The highlight contract: spans index the original text the client renders."""
    from tests.integration.test_meeting_flow import auth, create_and_join, stream_until_finals

    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        await ws.receive_json()
        await stream_until_finals(ws, frames=150, want=2)
    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

    whole = (
        await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    ).json()
    word = whole["segments"][0]["text"].split()[0].strip(".,")

    body = (
        await ws_client.http.get(
            f"/meetings/{meeting_id}/transcript", params={"q": word}, headers=auth(token)
        )
    ).json()

    by_id = {s["id"]: s["text"] for s in body["segments"]}
    assert body["matches"]
    for match in body["matches"]:
        text = by_id[match["segment_id"]]
        for start, end in match["spans"]:
            assert text[start:end].lower() == word.lower()


async def test_an_empty_query_returns_the_whole_transcript(ws_client, settings, tenants):
    """Clearing the search box must not look like a lost transcript."""
    from tests.integration.test_meeting_flow import auth, create_and_join, stream_until_finals

    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        await ws.receive_json()
        await stream_until_finals(ws, frames=150, want=2)
    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

    whole = (
        await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    ).json()
    blank = (
        await ws_client.http.get(
            f"/meetings/{meeting_id}/transcript", params={"q": "  "}, headers=auth(token)
        )
    ).json()

    assert len(blank["segments"]) == len(whole["segments"])
    assert blank["matches"] == []


async def test_search_does_not_cross_tenants(ws_client, settings, tenants):
    """A new query parameter is a new way to ask; tenancy still answers no."""
    from tests.conftest import host_token_for
    from tests.integration.test_meeting_flow import auth, create_and_join

    _, meeting_id, _ = await create_and_join(ws_client.http, settings, tenants["alpha"])
    intruder = host_token_for(settings, tenants["beta"])

    response = await ws_client.http.get(
        f"/meetings/{meeting_id}/transcript", params={"q": "budget"}, headers=auth(intruder)
    )

    assert response.status_code == 404
