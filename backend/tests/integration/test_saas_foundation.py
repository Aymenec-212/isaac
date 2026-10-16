"""AUTH-01..04 real PostgreSQL HTTP/session/tenant tests. No provider impersonation route."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mosaique.app.main import create_app
from mosaique.config.settings import Settings
from mosaique.identity.sessions import Sessions, digest
from mosaique.persistence.engine import get_sessionmaker
from mosaique.persistence.models.identity import Account, AccountSession

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:5173"


@pytest.fixture
async def enterprise(engine, settings):
    configured = Settings(
        database_url=settings.database_url,
        token_secret=settings.token_secret,
        environment="ci",
        application_mode="enterprise",
    )
    app = create_app(configured)
    async with AsyncClient(
        transport=ASGITransport(app, raise_app_exceptions=False), base_url=ORIGIN
    ) as client:
        yield client


async def login(client, email="owner@enterprise.test"):
    """Seed a server session in the database; never a production login backdoor."""
    from mosaique.domain.ids import new_id

    async with get_sessionmaker()() as s:
        a = Account(
            id=new_id(),
            issuer="https://test.invalid/",
            subject=new_id(),
            email=email,
            display_name="Test Owner",
            email_verified=True,
        )
        s.add(a)
        await s.flush()
        token = await s.run_sync(lambda db: Sessions(db).issue(a.id))
        await s.commit()
        account_id = a.id
    client.cookies.set("mosaique_session", token)
    response = await client.get("/saas/me")
    assert response.status_code == 200, response.text
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]})
    return account_id, token


async def workspace(client, name="Alpha"):
    response = await client.post("/saas/workspaces", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def invite(client, org, email):
    response = await client.post(f"/saas/workspaces/{org}/invitations", json={"email": email})
    assert response.status_code == 201, response.text
    return response.json()["token"]


async def test_opaque_session_csrf_profile_logout_and_expiry(enterprise):
    c = enterprise
    assert (await c.get("/saas/me")).status_code == 401
    _, token = await login(c)
    assert (await c.patch("/saas/me", json={"display_name": "Changed"})).status_code == 200
    assert (await c.get("/saas/me")).json()["display_name"] == "Changed"
    c.headers["Origin"] = "https://attacker.invalid"
    assert (await c.post("/saas/workspaces", json={"name": "Bad"})).status_code == 403
    c.headers["Origin"] = ORIGIN
    csrf = c.headers.pop("X-CSRF-Token")
    assert (await c.post("/saas/workspaces", json={"name": "Bad"})).status_code == 403
    c.headers["X-CSRF-Token"] = csrf
    assert (await c.post("/saas/logout")).status_code == 200
    c.cookies.set("mosaique_session", token)
    assert (await c.get("/saas/me")).status_code == 401
    _, token = await login(c)
    async with get_sessionmaker()() as db:
        row = await db.get(AccountSession, digest(token))
        row.last_seen_at = datetime.now(UTC) - timedelta(minutes=31)
        await db.commit()
    assert (await c.get("/saas/me")).status_code == 401
    _, token = await login(c)
    async with get_sessionmaker()() as db:
        row = await db.get(AccountSession, digest(token))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    assert (await c.get("/saas/me")).status_code == 401


async def test_invitation_switch_private_meeting_idor_and_revocation(enterprise):
    c = enterprise
    owner, owner_token = await login(c)
    alpha, beta = await workspace(c), await workspace(c, "Beta")
    invite_a = await invite(c, alpha, "member@test")
    invite_b = await invite(c, beta, "member@test")
    created = await c.post(f"/saas/workspaces/{alpha}/meetings", json={"title": "Private"})
    assert created.status_code == 201, created.text
    meeting = created.json()["id"]
    member, member_token = await login(c, "member@test")
    assert (await c.get(f"/saas/workspaces/{alpha}/members")).status_code == 404
    for token in (invite_a, invite_b):
        assert (await c.post("/saas/invitations/accept", json={"token": token})).status_code == 200
    assert (await c.post("/saas/invitations/accept", json={"token": invite_a})).status_code == 404
    assert {w["id"] for w in (await c.get("/saas/workspaces")).json()} == {alpha, beta}
    assert (await c.get(f"/saas/workspaces/{alpha}/meetings")).json() == []
    assert (await c.get(f"/saas/workspaces/{alpha}/meetings/{meeting}")).status_code == 404
    assert (await c.patch(f"/saas/workspaces/{alpha}", json={"name": "Hacked"})).status_code == 403
    c.cookies.set("mosaique_session", owner_token)
    c.headers["X-CSRF-Token"] = (await c.get("/saas/me")).json()["csrf_token"]
    assert (
        await c.put(
            f"/saas/workspaces/{alpha}/meetings/{meeting}/access/{member}", json={"allow": True}
        )
    ).status_code == 200
    events = (await c.get(f"/saas/workspaces/{alpha}/audit")).json()
    grant_event = next(e for e in events if e["action"] == "meeting.access_granted")
    assert grant_event["target_id"] == member and grant_event["context_id"] == meeting
    assert (await c.patch(f"/saas/workspaces/{alpha}", json={"name": "Renamed"})).status_code == 200
    c.cookies.set("mosaique_session", member_token)
    c.headers["X-CSRF-Token"] = (await c.get("/saas/me")).json()["csrf_token"]
    assert (await c.get(f"/saas/workspaces/{alpha}/meetings/{meeting}")).status_code == 200
    assert (await c.get(f"/saas/workspaces/{beta}/meetings/{meeting}")).status_code == 404
    assert (
        await c.put(
            f"/saas/workspaces/{alpha}/meetings/{meeting}/access/{owner}", json={"allow": True}
        )
    ).status_code == 403
    c.cookies.set("mosaique_session", owner_token)
    c.headers["X-CSRF-Token"] = (await c.get("/saas/me")).json()["csrf_token"]
    assert (
        await c.patch(f"/saas/workspaces/{alpha}/members/{member}", json={"role": None})
    ).status_code == 200
    reinvite = await invite(c, alpha, "member@test")
    c.cookies.set("mosaique_session", member_token)
    c.headers["X-CSRF-Token"] = (await c.get("/saas/me")).json()["csrf_token"]
    for path in (
        f"/saas/workspaces/{alpha}/members",
        f"/saas/workspaces/{alpha}/meetings",
        f"/saas/workspaces/{alpha}/meetings/{meeting}",
    ):
        assert (await c.get(path)).status_code == 404
    assert (await c.post("/saas/invitations/accept", json={"token": reinvite})).status_code == 200
    assert (await c.get(f"/saas/workspaces/{alpha}/meetings/{meeting}")).status_code == 404
    assert (await c.get(f"/saas/workspaces/{beta}/members")).status_code == 200


async def test_disabled_account_and_legacy_credentials_fail_closed(enterprise, settings):
    from mosaique.app.auth.tokens import issue_host_token

    c = enterprise
    actor, token = await login(c)
    async with get_sessionmaker()() as db:
        row = await db.get(Account, actor)
        row.disabled = True
        await db.commit()
    assert (await c.get("/saas/me")).status_code == 401
    c.cookies.clear()
    c.headers["Authorization"] = "Bearer " + issue_host_token(
        user_id=actor, organization_id="anything", secret=settings.token_secret, ttl_hours=1
    )
    assert (await c.get("/saas/workspaces")).status_code == 401
    assert (await c.get("/meetings")).status_code == 404
    # No prototype API/WS is mounted in the enterprise application.
    assert (await c.get("/saas/me")).headers["cache-control"] == "no-store"


async def test_last_owner_invite_mismatch_and_new_session_persistence(enterprise):
    c = enterprise
    owner, owner_token = await login(c)
    org = await workspace(c)
    assert (
        await c.patch(f"/saas/workspaces/{org}/members/{owner}", json={"role": "member"})
    ).status_code == 403
    invitation = await invite(c, org, "invited@test")
    await login(c, "wrong@test")
    assert (await c.post("/saas/invitations/accept", json={"token": invitation})).status_code == 403
    c.cookies.set("mosaique_session", owner_token)
    assert (await c.get("/saas/workspaces")).json()[0]["id"] == org
    # Read through a fresh DB session, not the HTTP request's identity map.
    async with get_sessionmaker()() as db:
        account = (await db.scalars(select(Account).where(Account.id == owner))).one()
        assert account.email == "owner@enterprise.test"


async def test_concurrent_last_owner_and_invitation_redemption(engine, settings):
    import asyncio
    from threading import Barrier

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from mosaique.domain.errors import Forbidden, NotFound
    from mosaique.domain.ids import new_id
    from mosaique.workspaces.service import Workspaces

    sync_engine = create_engine(settings.sync_database_url)
    try:
        with Session(sync_engine) as db, db.begin():
            owners = [
                Account(
                    id=new_id(),
                    issuer="https://test.invalid/",
                    subject=new_id(),
                    email=f"{new_id()}@test",
                    email_verified=True,
                )
                for _ in range(2)
            ]
            guest = Account(
                id=new_id(),
                issuer="https://test.invalid/",
                subject=new_id(),
                email=f"{new_id()}@test",
                email_verified=True,
            )
            db.add_all([*owners, guest])
            db.flush()
            service = Workspaces(db)
            org = service.create(owners[0].id, "Concurrent").id
            service.accept(owners[1].id, service.invite(owners[0].id, org, owners[1].email))
            service.change_member(owners[0].id, org, owners[1].id, role="owner")
            owner_ids = [owner.id for owner in owners]
            guest_id, guest_email = guest.id, guest.email
            invitation = service.invite(owners[0].id, org, guest.email)
        barrier = Barrier(2)

        def demote(actor):
            barrier.wait(timeout=5)
            try:
                with Session(sync_engine) as db, db.begin():
                    Workspaces(db).change_member(actor, org, actor, role="member")
                return "demoted"
            except Forbidden:
                return "last-owner-denied"

        results = await asyncio.gather(*(asyncio.to_thread(demote, actor) for actor in owner_ids))
        assert sorted(results) == ["demoted", "last-owner-denied"]
        # The original invitation may have been invalidated by the inviter's demotion.
        with Session(sync_engine) as db, db.begin():
            from mosaique.persistence.models.identity import Membership

            active_owner = db.scalar(
                select(Membership.account_id).where(
                    Membership.organization_id == org, Membership.role == "owner"
                )
            )
            invitation = Workspaces(db).invite(active_owner, org, guest_email)
        barrier = Barrier(2)

        def redeem():
            barrier.wait(timeout=5)
            try:
                with Session(sync_engine) as db, db.begin():
                    Workspaces(db).accept(guest_id, invitation)
                return "accepted"
            except NotFound:
                return "replay-denied"

        results = await asyncio.gather(asyncio.to_thread(redeem), asyncio.to_thread(redeem))
        assert sorted(results) == ["accepted", "replay-denied"]
    finally:
        sync_engine.dispose()


async def test_invitation_revocation_audit_and_activity(enterprise):
    c = enterprise
    actor, token = await login(c)
    org = await workspace(c)
    invitation = await invite(c, org, "revoked@test")
    outstanding = (await c.get(f"/saas/workspaces/{org}/invitations")).json()
    assert len(outstanding) == 1
    assert "token" not in outstanding[0]
    assert (
        await c.delete(f"/saas/workspaces/{org}/invitations/{outstanding[0]['id']}")
    ).status_code == 200
    assert (await c.get(f"/saas/workspaces/{org}/invitations")).json() == []
    events = (await c.get(f"/saas/workspaces/{org}/audit")).json()
    assert {e["action"] for e in events} >= {
        "workspace.created",
        "invitation.created",
        "invitation.revoked",
    }
    async with get_sessionmaker()() as db:
        row = await db.get(AccountSession, digest(token))
        deadline = row.expires_at
        row.last_seen_at = datetime.now(UTC) - timedelta(minutes=29)
        await db.commit()
    assert (await c.post("/saas/session/activity")).status_code == 200
    async with get_sessionmaker()() as db:
        row = await db.get(AccountSession, digest(token))
        assert row.expires_at == deadline
        assert row.last_seen_at > datetime.now(UTC) - timedelta(seconds=10)
        second_token = await db.run_sync(lambda s: Sessions(s).issue(actor))
        await db.commit()
    assert (await c.post("/saas/logout-all")).status_code == 200
    c.cookies.set("mosaique_session", second_token)
    assert (await c.get("/saas/me")).status_code == 401
    await login(c, "revoked@test")
    assert (await c.post("/saas/invitations/accept", json={"token": invitation})).status_code == 404
    for path in ("invitations", "audit"):
        assert (await c.get(f"/saas/workspaces/{org}/{path}")).status_code == 404


async def test_missing_identity_configuration_is_actionable(enterprise):
    response = await enterprise.get("/readyz")
    assert response.status_code == 503
    identity = next(d for d in response.json()["dependencies"] if d["name"] == "identity")
    assert identity["state"] == "unavailable"
    assert (await enterprise.get("/auth/status")).json() == {"configured": False}
    error = await enterprise.get("/auth/login", headers={"Accept": "text/html"})
    assert error.status_code == 503
    assert "Retour à Mosaïque" in error.text


async def test_commit_failure_never_reports_success(enterprise, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    from mosaique.persistence.models import Organization

    c = enterprise
    await login(c)

    async def failed_commit(self):
        raise RuntimeError("simulated commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", failed_commit)
        response = await c.post("/saas/workspaces", json={"name": "Must roll back"})
        assert response.status_code == 500
    async with get_sessionmaker()() as db:
        assert not list(
            await db.scalars(select(Organization).where(Organization.name == "Must roll back"))
        )


async def test_grant_target_does_not_reveal_foreign_accounts(enterprise):
    from mosaique.domain.ids import new_id

    c = enterprise
    _, owner_token = await login(c)
    org = await workspace(c)
    meeting = (await c.post(f"/saas/workspaces/{org}/meetings", json={"title": "Private"})).json()[
        "id"
    ]
    foreign, _ = await login(c, "foreign@test")
    c.cookies.set("mosaique_session", owner_token)
    c.headers["X-CSRF-Token"] = (await c.get("/saas/me")).json()["csrf_token"]
    responses = [
        await c.put(
            f"/saas/workspaces/{org}/meetings/{meeting}/access/{target}", json={"allow": True}
        )
        for target in (foreign, new_id())
    ]
    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json()["error"]["message"] == responses[1].json()["error"]["message"]


async def test_reinvitation_does_not_restore_organizer_authority(enterprise):
    c = enterprise
    owner, owner_token = await login(c)
    org = await workspace(c)
    invitation = await invite(c, org, "organizer@test")
    organizer, organizer_token = await login(c, "organizer@test")
    assert (await c.post("/saas/invitations/accept", json={"token": invitation})).status_code == 200
    root = f"/saas/workspaces/{org}/meetings"
    meeting = (await c.post(root, json={"title": "Revoked organizer"})).json()["id"]
    detail = f"{root}/{meeting}"
    assert (await c.get(detail)).status_code == 200
    assert (await c.get(detail + "/access")).status_code == 200

    async def switch(token):
        c.cookies.set("mosaique_session", token)
        c.headers["X-CSRF-Token"] = (await c.get("/saas/me")).json()["csrf_token"]

    await switch(owner_token)
    assert (await c.get(detail)).status_code == 404  # Owner is not an implicit viewer.
    assert (
        await c.patch(f"/saas/workspaces/{org}/members/{organizer}", json={"role": None})
    ).status_code == 200
    assert (await c.post(detail + "/restore-organizer")).status_code == 404
    invitation = await invite(c, org, "organizer@test")
    await switch(organizer_token)
    assert (await c.get(root)).status_code == 404
    assert (await c.post("/saas/invitations/accept", json={"token": invitation})).status_code == 200
    assert (await c.get(root)).json() == []
    assert (await c.get(detail)).status_code == 404
    assert (await c.get(detail + "/access")).status_code == 404
    assert (await c.put(detail + f"/access/{owner}", json={"allow": True})).status_code == 404
    assert (await c.post(detail + "/restore-organizer")).status_code == 403
    await switch(owner_token)
    assert (await c.post(detail + "/restore-organizer")).status_code == 200
    events = (await c.get(f"/saas/workspaces/{org}/audit")).json()
    restored = [e for e in events if e["action"] == "meeting.organizer_restored"]
    assert len(restored) == 1
    assert restored[0]["target_id"] == organizer and restored[0]["context_id"] == meeting
    await switch(organizer_token)
    assert [m["id"] for m in (await c.get(root)).json()] == [meeting]
    assert (await c.get(detail)).status_code == 200
    assert (await c.get(detail + "/access")).status_code == 200
    assert (await c.put(detail + f"/access/{owner}", json={"allow": True})).status_code == 200
