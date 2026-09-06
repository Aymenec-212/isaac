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
