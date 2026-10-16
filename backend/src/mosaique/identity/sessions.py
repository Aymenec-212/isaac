"""Opaque, revocable browser sessions; no identity-provider or HTTP dependency."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mosaique.domain.errors import Forbidden, InvalidToken
from mosaique.identity.accounts import identity_key, lock_identity
from mosaique.persistence.models.identity import Account, AccountSession, RevokedProviderSession


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class Sessions:
    def __init__(self, db: Session) -> None:
        self.db = db

    def issue(
        self, account_id: str, previous: str | None = None, *, provider_sid: str | None = None
    ) -> str:
        account = self.db.get(Account, account_id, populate_existing=True)
        if account is None or account.disabled:
            raise InvalidToken()
        sid_hash = digest(provider_sid) if provider_sid else None
        if provider_sid:
            lock_identity(self.db, account.issuer, account.subject)
        if (
            sid_hash
            and self.db.get(
                RevokedProviderSession, (identity_key(account.issuer, account.subject), sid_hash)
            )
            is not None
        ):
            raise InvalidToken("Provider session was revoked; sign in again")
        if previous:
            self.revoke(previous)
        now = datetime.now(UTC)
        # Opportunistic bounded cleanup is handled by an operator command, not every login.
        token = secrets.token_urlsafe(32)
        self.db.add(
            AccountSession(
                token_hash=digest(token),
                account_id=account_id,
                provider_sid_hash=sid_hash,
                csrf_token=secrets.token_urlsafe(32),
                last_seen_at=now,
                expires_at=now + timedelta(hours=12),
            )
        )
        self.db.flush()
        return token

    def authenticate(
        self, token: str | None, csrf: str | None = None, *, mutate: bool = False
    ) -> tuple[Account, AccountSession]:
        if not token or len(token) > 128:
            raise InvalidToken()
        row = self.db.scalar(
            select(AccountSession)
            .where(AccountSession.token_hash == digest(token))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = datetime.now(UTC)
        if (
            row is None
            or utc(row.expires_at) <= now
            or utc(row.last_seen_at) <= now - timedelta(minutes=30)
        ):
            raise InvalidToken()
        account = self.db.get(Account, row.account_id, populate_existing=True)
        if account is None or account.disabled:
            raise InvalidToken()
        if mutate and (not csrf or not secrets.compare_digest(row.csrf_token, csrf)):
            raise Forbidden("Refresh the page and retry (CSRF validation failed)")
        row.last_seen_at = now
        self.db.flush()
        return account, row

    def revoke(self, token: str) -> None:
        self.db.execute(delete(AccountSession).where(AccountSession.token_hash == digest(token)))
