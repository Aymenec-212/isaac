"""Authlib OIDC adapter. Tokens are validated here and discarded after login.

Temporary OIDC secrets are persisted server-side; cookies contain random handles.
No network request runs inside an application database transaction.
"""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import jwt
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete, func, select

from mosaique.app.api.dependencies import SettingsDep
from mosaique.app.api.saas import COOKIE
from mosaique.config.settings import Settings
from mosaique.domain.errors import ErrorCode, InvalidToken, MosaiqueError
from mosaique.identity.accounts import identity_key, lock_identity, resolve_account
from mosaique.identity.sessions import Sessions, digest, utc
from mosaique.persistence.engine import session_scope
from mosaique.persistence.models.identity import (
    Account,
    AccountSession,
    LoginAttempt,
    RevokedProviderSession,
)

router = APIRouter(prefix="/auth", tags=["identity"])
BROWSER_COOKIE = "mosaique_login"


def client(settings: Settings) -> Any:
    if not settings.oidc_issuer:
        raise MosaiqueError(
            ErrorCode.IDENTITY_UNAVAILABLE,
            "Sign-in is not configured. Contact your administrator.",
        )
    oauth = OAuth()
    return oauth.register(
        "auth0",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=settings.oidc_issuer + ".well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile",
            "code_challenge_method": "S256",
            "timeout": 10.0,
        },
    )


async def metadata(provider: Any, settings: Settings) -> None:
    config = await provider.load_server_metadata()
    if config.get("issuer") != settings.oidc_issuer:
        raise InvalidToken("Identity issuer mismatch")
    # Auth0 is configured for asymmetric signing; never accept a client-secret JWT.
    provider.server_metadata["id_token_signing_alg_values_supported"] = ["RS256"]


@router.get("/status")
async def status(settings: SettingsDep) -> dict[str, bool]:
    return {"configured": bool(settings.oidc_issuer)}


@router.get("/login")
async def login(request: Request, settings: SettingsDep) -> RedirectResponse:
    provider = request.app.state.oidc_provider
    if provider is None:
        raise MosaiqueError(ErrorCode.IDENTITY_UNAVAILABLE, "Sign-in is not configured")
    state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    try:
        await metadata(provider, settings)
        result = await provider.create_authorization_url(
            settings.public_origin + "/api/auth/callback",
            state=state,
            nonce=nonce,
            code_verifier=verifier,
            prompt="login",
            max_age=0,
        )
    except Exception:
        # No provider descriptions, response bodies or credentials reach the browser/logs.
        raise MosaiqueError(
            ErrorCode.IDENTITY_UNAVAILABLE, "Sign-in provider is unavailable. Retry shortly."
        ) from None
    async with session_scope() as db:
        now = datetime.now(UTC)
        expired = select(LoginAttempt.state_hash).where(LoginAttempt.expires_at <= now).limit(100)
        await db.execute(delete(LoginAttempt).where(LoginAttempt.state_hash.in_(expired)))
        old = request.cookies.get(BROWSER_COOKIE)
        if old:
            await db.execute(delete(LoginAttempt).where(LoginAttempt.browser_hash == digest(old)))
        count = await db.scalar(select(func.count()).select_from(LoginAttempt))
        if count is not None and count >= 1000:
            raise MosaiqueError(ErrorCode.RATE_LIMITED, "Too many sign-in attempts. Retry shortly.")
        db.add(
            LoginAttempt(
                state_hash=digest(state),
                browser_hash=digest(browser),
                nonce=nonce,
                verifier=verifier,
                expires_at=now + timedelta(minutes=10),
            )
        )
    response = RedirectResponse(result["url"], status_code=302)
    response.set_cookie(
        BROWSER_COOKIE,
        browser,
        max_age=600,
        httponly=True,
        secure=settings.public_origin.startswith("https:"),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/callback")
async def callback(request: Request, settings: SettingsDep) -> RedirectResponse:
    state, browser, code = (
        request.query_params.get("state"),
        request.cookies.get(BROWSER_COOKIE),
        request.query_params.get("code"),
    )
    if not state or len(state) > 128 or not browser or not code or len(code) > 4096:
        raise InvalidToken("Sign-in expired or cancelled. Start again.")
    async with session_scope() as db:
        attempt = await db.scalar(
            select(LoginAttempt).where(LoginAttempt.state_hash == digest(state)).with_for_update()
        )
        if (
            attempt is None
            or utc(attempt.expires_at) <= datetime.now(UTC)
            or not secrets.compare_digest(attempt.browser_hash, digest(browser))
        ):
            raise InvalidToken("Sign-in expired or cancelled. Start again.")
        nonce, verifier = attempt.nonce, attempt.verifier
        await db.delete(attempt)
    # State is single-use even if the provider fails. A retry starts a new flow.
    provider = request.app.state.oidc_provider
    if provider is None:
        raise MosaiqueError(ErrorCode.IDENTITY_UNAVAILABLE, "Sign-in is not configured")
    try:
        await metadata(provider, settings)
        token = await provider.fetch_access_token(
            redirect_uri=settings.public_origin + "/api/auth/callback",
            code=code,
            code_verifier=verifier,
        )
        claims = await provider.parse_id_token(
            token,
            nonce=nonce,
            claims_options={"iss": {"essential": True, "values": [settings.oidc_issuer]}},
            leeway=30,
        )
        if (
            not claims
            or not isinstance(claims.get("sub"), str)
            or not 0 < len(claims["sub"]) <= 255
            or not isinstance(claims.get("email"), str)
            or not 0 < len(claims["email"]) <= 320
            or not isinstance(claims.get("email_verified"), bool)
            or not isinstance(claims.get("sid"), str)
            or not 0 < len(claims["sid"]) <= 255
        ):
            raise ValueError("Missing identity claims")
    except Exception:
        raise InvalidToken("Sign-in could not be verified. Start again.") from None
    async with session_scope() as db:
        account_id = await db.run_sync(
            lambda s: resolve_account(
                s,
                issuer=str(settings.oidc_issuer),
                subject=claims["sub"],
                email=claims["email"],
                email_verified=claims["email_verified"],
                initial_name=str(claims.get("name") or ""),
            )
        )
        session_token = await db.run_sync(
            lambda s: Sessions(s).issue(
                account_id, previous=request.cookies.get(COOKIE), provider_sid=claims["sid"]
            )
        )
    response = RedirectResponse(settings.public_origin + "/", status_code=303)
    response.delete_cookie(BROWSER_COOKIE, path="/")
    response.set_cookie(
        COOKIE,
        session_token,
        max_age=12 * 3600,
        httponly=True,
        secure=settings.public_origin.startswith("https:"),
        samesite="lax",
        path="/",
    )
    return response


@router.post("/backchannel-logout")
async def backchannel_logout(request: Request, settings: SettingsDep) -> Response:
    provider = request.app.state.oidc_provider
    if provider is None:
        raise InvalidToken()
    # Bound form payload without requiring a multipart parser for one URL-encoded field.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            raise InvalidToken()
    try:
        values = parse_qs(raw.decode(), strict_parsing=True)
        signed = values["logout_token"]
        if len(signed) != 1:
            raise ValueError("Ambiguous token")
        await metadata(provider, settings)
        header = jwt.get_unverified_header(signed[0])
        if header.get("alg") != "RS256":
            raise ValueError("Invalid algorithm")
        keys = await provider.fetch_jwk_set()
        matches = [k for k in keys["keys"] if k.get("kid") == header.get("kid")]
        if not matches:
            keys = await provider.fetch_jwk_set(force=True)
            matches = [k for k in keys["keys"] if k.get("kid") == header.get("kid")]
        if len(matches) != 1:
            raise ValueError("Unknown key")
        claims = jwt.decode(
            signed[0],
            jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key,
            algorithms=["RS256"],
            issuer=settings.oidc_issuer,
            audience=settings.oidc_client_id,
            options={"require": ["iss", "aud", "iat", "exp", "jti", "sub", "sid", "events"]},
        )
        if (
            time.time() - claims["iat"] > 120
            or "nonce" in claims
            or claims["events"] != {"http://schemas.openid.net/event/backchannel-logout": {}}
            or not isinstance(claims["sub"], str)
            or not isinstance(claims["sid"], str)
            or not 0 < len(claims["sid"]) <= 255
            or not 0 < len(claims["sub"]) <= 255
        ):
            raise ValueError("Invalid logout claims")
    except Exception:
        raise InvalidToken("Invalid provider logout event") from None
    async with session_scope() as db:
        # The identity lock also covers logout arriving before first account creation.
        await db.run_sync(lambda s: lock_identity(s, str(settings.oidc_issuer), claims["sub"]))
        key = (identity_key(str(settings.oidc_issuer), claims["sub"]), digest(claims["sid"]))
        if await db.get(RevokedProviderSession, key) is None:
            db.add(RevokedProviderSession(identity_hash=key[0], sid_hash=key[1]))
        account = await db.scalar(
            select(Account).where(
                Account.issuer == settings.oidc_issuer, Account.subject == claims["sub"]
            )
        )
        if account is not None:
            await db.execute(
                delete(AccountSession).where(
                    AccountSession.account_id == account.id,
                    AccountSession.provider_sid_hash == key[1],
                )
            )
    return Response(status_code=200, headers={"Cache-Control": "no-store"})
