"""Signed token issue and verification (tech spec 13.1).

Slice 0 issues host tokens for a pre-provisioned pilot account (blueprint R-2).
Magic-link login is deferred to Slice 7; the token *boundary* exists now so
nothing downstream has to change when the login mechanism arrives.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from mosaique.domain.errors import InvalidToken

ALGORITHM = "HS256"
PrincipalKind = Literal["host", "participant"]


@dataclass(frozen=True)
class Principal:
    """Who is making this request, and which tenant they belong to."""

    kind: PrincipalKind
    subject_id: str  # user_id for a host, participant_id for a guest
    organization_id: str
    meeting_id: str | None = None  # guests are bound to one meeting

    @property
    def is_host(self) -> bool:
        return self.kind == "host"


def issue_host_token(*, user_id: str, organization_id: str, secret: str, ttl_hours: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "kind": "host",
        "sub": user_id,
        "org": organization_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def issue_session_token(
    *, participant_id: str, organization_id: str, meeting_id: str, secret: str, ttl_hours: int
) -> str:
    now = datetime.now(UTC)
    payload = {
        "kind": "participant",
        "sub": participant_id,
        "org": organization_id,
        "mtg": meeting_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_token(token: str, *, secret: str) -> Principal:
    """Decode and validate. Raises InvalidToken for anything malformed or expired."""
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidToken() from exc

    kind = payload.get("kind")
    subject = payload.get("sub")
    organization_id = payload.get("org")
    if kind not in ("host", "participant") or not subject or not organization_id:
        raise InvalidToken("Token is missing required claims")

    return Principal(
        kind=kind,
        subject_id=subject,
        organization_id=organization_id,
        meeting_id=payload.get("mtg"),
    )


def new_invite_token() -> str:
    """Random 128-bit invite token (tech spec 13.1). Stored hashed, never in plain text."""
    return secrets.token_urlsafe(16)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
