"""Deterministic signed OIDC provider boundary. Real Auth0 remains a separate gate."""

import base64
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mosaique.app.auth import oidc
from mosaique.app.main import create_app
from mosaique.config.settings import Settings
from mosaique.persistence.engine import get_sessionmaker
from mosaique.persistence.models.identity import Account, LoginAttempt, RevokedProviderSession

pytestmark = pytest.mark.integration
ISSUER = "https://provider.test/"
ORIGIN = "https://app.test"


def b64(number):
    return (
        base64.urlsafe_b64encode(number.to_bytes((number.bit_length() + 7) // 8, "big"))
        .rstrip(b"=")
        .decode()
    )


@pytest.fixture
async def provider(engine, settings, monkeypatch):
    configured = Settings(
        database_url=settings.database_url,
        token_secret=settings.token_secret,
        environment="ci",
        application_mode="enterprise",
        public_origin=ORIGIN,
        oidc_issuer=ISSUER,
        oidc_client_id="client",
        oidc_client_secret="dummy-secret",
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_numbers()
    behavior = {
        "nonce": "",
        "issuer": ISSUER,
        "audience": "client",
        "subject": "auth0|one",
        "wrong_key": False,
        "expired": False,
        "verifier": None,
    }

    async def handle(request):
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "authorize",
                    "token_endpoint": ISSUER + "oauth/token",
                    "jwks_uri": ISSUER + "jwks",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if request.url.path == "/jwks":
            return httpx.Response(
                200,
                json={
                    "keys": [
                        {
                            "kty": "RSA",
                            "kid": "one",
                            "use": "sig",
                            "alg": "RS256",
                            "n": b64(public.n),
                            "e": b64(public.e),
                        }
                    ]
                },
            )
        if request.url.path == "/oauth/token":
            nonce = behavior["nonce"]
            if "exchange_entered" in behavior:
                behavior["exchange_entered"].set()
                await behavior["exchange_release"].wait()
            data = parse_qs(request.content.decode())
            behavior["verifier"] = data["code_verifier"][0]
            now = int(time.time())
            claims = {
                "iss": behavior["issuer"],
                "aud": behavior["audience"],
                "sub": behavior["subject"],
                "nonce": nonce,
                "iat": now,
                "exp": now - 90 if behavior["expired"] else now + 600,
                "email": "same@email.test",
                "email_verified": True,
                "name": "Camille",
                "sid": "provider-session",
            }
            signing_key = (
                rsa.generate_private_key(public_exponent=65537, key_size=2048)
                if behavior["wrong_key"]
                else key
            )
            signed = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "one"})
            return httpx.Response(
                200, json={"access_token": "discard-me", "token_type": "Bearer", "id_token": signed}
            )
        raise AssertionError(f"Unexpected provider request {request.url}")

    async with get_sessionmaker()() as db:
        await db.execute(delete(LoginAttempt))
        await db.execute(delete(RevokedProviderSession))
        await db.execute(delete(Account).where(Account.issuer == ISSUER))
        await db.commit()

    behavior["key"] = key

    actual_client = oidc.client

    def create(config):
        instance = actual_client(config)
        instance.client_kwargs["transport"] = httpx.MockTransport(handle)
        return instance

    monkeypatch.setattr(oidc, "client", create)
    behavior["app"] = create_app(configured)
    async with AsyncClient(transport=ASGITransport(behavior["app"]), base_url=ORIGIN) as c:
        yield c, behavior


async def start(c, behavior):
    response = await c.get("/auth/login")
    assert response.status_code == 302, response.text
    params = parse_qs(urlsplit(response.headers["location"]).query)
    behavior["nonce"] = params["nonce"][0]
    assert params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == [ORIGIN + "/api/auth/callback"]
    assert (
        "HttpOnly" in response.headers["set-cookie"] and "Secure" in response.headers["set-cookie"]
    )
    return params["state"][0], params["code_challenge"][0]


async def finish(c, state):
    return await c.get("/auth/callback", params={"state": state, "code": "one-use-code"})


async def test_signed_oidc_pkce_rotation_and_no_email_merge(provider):
    import hashlib

    c, behavior = provider
    state, challenge = await start(c, behavior)
    first = await finish(c, state)
    assert first.status_code == 303, first.text
    assert (
        challenge
        == base64.urlsafe_b64encode(hashlib.sha256(behavior["verifier"].encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    old_token = c.cookies.get("mosaique_session")
    account = (await c.get("/saas/me")).json()
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    new_token = c.cookies.get("mosaique_session")
    assert new_token != old_token
    c.cookies.set("mosaique_session", old_token, domain="app.test", path="/")
    assert (await c.get("/saas/me")).status_code == 401
    c.cookies.set("mosaique_session", new_token, domain="app.test", path="/")
    assert (await c.get("/saas/me")).json()["id"] == account["id"]
    behavior["subject"] = "auth0|another"
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    assert (await c.get("/saas/me")).json()["id"] != account["id"]
    async with get_sessionmaker()() as db:
        rows = list(await db.scalars(select(Account).where(Account.issuer == ISSUER)))
        assert len(rows) == 2
    assert (await finish(c, state)).status_code == 401


@pytest.mark.parametrize("bad", ["issuer", "audience", "nonce", "wrong_key", "expired"])
async def test_oidc_rejects_invalid_identity(provider, bad):
    c, behavior = provider
    state, _ = await start(c, behavior)
    behavior[bad] = True if bad in ("wrong_key", "expired") else "wrong"
    assert (await finish(c, state)).status_code == 401
    assert (await c.get("/saas/me")).status_code == 401
    assert (await finish(c, state)).status_code == 401  # consumed on failed exchange


async def test_state_browser_binding_expiry_and_disable(provider):
    from datetime import UTC, datetime, timedelta

    c, behavior = provider
    state, _ = await start(c, behavior)
    saved = c.cookies.get("mosaique_login")
    c.cookies.clear()
    assert (await finish(c, state)).status_code == 401
    c.cookies.set("mosaique_login", saved)
    async with get_sessionmaker()() as db:
        attempt = (await db.scalars(select(LoginAttempt))).one()
        attempt.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    assert (await finish(c, state)).status_code == 401
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    async with get_sessionmaker()() as db:
        account = (await db.scalars(select(Account).where(Account.issuer == ISSUER))).one()
        account.disabled = True
        await db.commit()
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 401


async def test_signed_provider_logout_revokes_session_and_fences_late_login(provider):
    c, behavior = provider
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    # A second callback is already in flight when the provider revokes this SID.
    late_state, _ = await start(c, behavior)
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": "client",
        "sub": "auth0|one",
        "sid": "provider-session",
        "iat": now,
        "exp": now + 120,
        "jti": "unique-event",
        "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
    }
    signed = jwt.encode(payload, behavior["key"], algorithm="RS256", headers={"kid": "one"})
    assert (
        await c.post("/auth/backchannel-logout", data={"logout_token": signed})
    ).status_code == 200
    assert (await c.get("/saas/me")).status_code == 401
    assert (await finish(c, late_state)).status_code == 401
    assert (
        await c.post("/auth/backchannel-logout", data={"logout_token": signed})
    ).status_code == 200
    for change in (
        {"aud": "foreign"},
        {"nonce": "not-a-logout"},
        {"events": {}},
        {"iat": now - 200},
    ):
        invalid = jwt.encode(
            {**payload, **change}, behavior["key"], algorithm="RS256", headers={"kid": "one"}
        )
        assert (
            await c.post("/auth/backchannel-logout", data={"logout_token": invalid})
        ).status_code == 401


async def test_logout_before_first_account_creation_fences_callback(provider):
    c, behavior = provider
    state, _ = await start(c, behavior)
    now = int(time.time())
    signed = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "client",
            "sub": "auth0|one",
            "sid": "provider-session",
            "iat": now,
            "exp": now + 120,
            "jti": "logout-before-account",
            "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        },
        behavior["key"],
        algorithm="RS256",
        headers={"kid": "one"},
    )
    assert (
        await c.post("/auth/backchannel-logout", data={"logout_token": signed})
    ).status_code == 200
    assert (await finish(c, state)).status_code == 401
    async with get_sessionmaker()() as db:
        assert not list(await db.scalars(select(Account).where(Account.issuer == ISSUER)))


@pytest.mark.parametrize("endpoint", ["logout", "logout-all"])
async def test_logout_cancels_callback_during_exchange(provider, endpoint):
    import asyncio

    c, behavior = provider
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    c.headers.update(
        {"Origin": ORIGIN, "X-CSRF-Token": (await c.get("/saas/me")).json()["csrf_token"]}
    )
    state, _ = await start(c, behavior)
    behavior["exchange_entered"] = asyncio.Event()
    behavior["exchange_release"] = asyncio.Event()
    pending = asyncio.create_task(finish(c, state))
    try:
        await asyncio.wait_for(behavior["exchange_entered"].wait(), 5)
        assert (await c.post(f"/saas/{endpoint}")).status_code == 200
        assert (await c.get("/saas/me")).status_code == 401
        behavior["exchange_release"].set()
        response = await asyncio.wait_for(pending, 5)
        assert response.status_code == 401, response.text
        assert (await c.get("/saas/me")).status_code == 401
    finally:
        behavior["exchange_release"].set()
        await asyncio.wait_for(pending, 5)
    del behavior["exchange_entered"], behavior["exchange_release"]
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    assert (await c.get("/saas/me")).status_code == 200


@pytest.mark.parametrize("endpoint", ["logout", "logout-all"])
@pytest.mark.parametrize("stage", ["before-validation", "before-insert"])
async def test_logout_serializes_with_session_issuance(provider, monkeypatch, endpoint, stage):
    import asyncio

    from sqlalchemy.util.concurrency import await_only

    from mosaique.identity.sessions import Sessions

    c, behavior = provider
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    c.headers.update(
        {"Origin": ORIGIN, "X-CSRF-Token": (await c.get("/saas/me")).json()["csrf_token"]}
    )
    state, _ = await start(c, behavior)
    entered, release, logout_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    method = "complete_login" if stage == "before-validation" else "issue"
    original, original_logout = getattr(Sessions, method), Sessions.logout

    def pause(self, *args, **kwargs):
        entered.set()
        await_only(release.wait())
        return original(self, *args, **kwargs)

    def observe_logout(self, *args, **kwargs):
        logout_entered.set()
        return original_logout(self, *args, **kwargs)

    monkeypatch.setattr(Sessions, method, pause)
    monkeypatch.setattr(Sessions, "logout", observe_logout)
    callback = asyncio.create_task(finish(c, state))
    logout = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        logout = asyncio.create_task(c.post(f"/saas/{endpoint}"))
        await asyncio.wait_for(logout_entered.wait(), 5)
        if stage == "before-validation":
            # Logout wins before the callback enters the atomic authorization boundary.
            assert (await asyncio.wait_for(logout, 5)).status_code == 200
            assert (await c.get("/saas/me")).status_code == 401
        release.set()
        result = await asyncio.wait_for(callback, 5)
        assert result.status_code == (401 if stage == "before-validation" else 303)
        # When issuance holds the locks first, logout waits and revokes the issued session.
        assert (await asyncio.wait_for(logout, 5)).status_code == 200
        assert (await c.get("/saas/me")).status_code == 401
    finally:
        release.set()
        await asyncio.wait_for(callback, 5)
        if logout:
            await asyncio.wait_for(logout, 5)
    monkeypatch.setattr(Sessions, method, original)
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    assert (await c.get("/saas/me")).status_code == 200


async def test_logout_all_cancels_unknown_identity_in_other_browser(provider):
    import asyncio

    c, behavior = provider
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    c.headers.update(
        {"Origin": ORIGIN, "X-CSRF-Token": (await c.get("/saas/me")).json()["csrf_token"]}
    )
    async with AsyncClient(transport=ASGITransport(behavior["app"]), base_url=ORIGIN) as other:
        state, _ = await start(other, behavior)
        behavior["exchange_entered"], behavior["exchange_release"] = (
            asyncio.Event(),
            asyncio.Event(),
        )
        pending = asyncio.create_task(finish(other, state))
        try:
            await asyncio.wait_for(behavior["exchange_entered"].wait(), 5)
            assert (await c.post("/saas/logout-all")).status_code == 200
            behavior["exchange_release"].set()
            assert (await asyncio.wait_for(pending, 5)).status_code == 401
            assert (await other.get("/saas/me")).status_code == 401
        finally:
            behavior["exchange_release"].set()
            await asyncio.wait_for(pending, 5)
        del behavior["exchange_entered"], behavior["exchange_release"]
        state, _ = await start(other, behavior)
        assert (await finish(other, state)).status_code == 303


@pytest.mark.parametrize("endpoint", ["logout", "logout-all"])
async def test_new_login_after_logout_survives_older_exchange(provider, endpoint):
    import asyncio

    c, behavior = provider
    state, _ = await start(c, behavior)
    assert (await finish(c, state)).status_code == 303
    c.headers.update(
        {"Origin": ORIGIN, "X-CSRF-Token": (await c.get("/saas/me")).json()["csrf_token"]}
    )
    state, _ = await start(c, behavior)
    entered, release = asyncio.Event(), asyncio.Event()
    behavior.update(exchange_entered=entered, exchange_release=release)
    old_callback = asyncio.create_task(finish(c, state))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert (await c.post(f"/saas/{endpoint}")).status_code == 200
        del behavior["exchange_entered"], behavior["exchange_release"]
        new_state, _ = await start(c, behavior)
        assert (await finish(c, new_state)).status_code == 303
        new_token = c.cookies.get("mosaique_session")
        release.set()
        assert (await asyncio.wait_for(old_callback, 5)).status_code == 401
        assert c.cookies.get("mosaique_session") == new_token
        assert (await c.get("/saas/me")).status_code == 200
    finally:
        release.set()
        await asyncio.wait_for(old_callback, 5)
