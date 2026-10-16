"""Opaque, revocable browser sessions; no identity-provider or HTTP dependency."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mosaique.domain.errors import ErrorCode, Forbidden, InvalidToken, MosaiqueError
from mosaique.identity.accounts import identity_key, lock_identity, resolve_account
from mosaique.persistence.models.identity import (
    LOGIN_GENERATION,
    Account,
    AccountSession,
    BrowserLogin,
    LoginAttempt,
    RevokedProviderSession,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


@dataclass(frozen=True)
class LoginTicket:
    browser_hash: str
    browser_generation: int
    login_generation: int
    expires_at: datetime


class Sessions:
    def __init__(self, db: Session) -> None:
        self.db = db

    def issue(
        self,
        account_id: str,
        previous: str | None = None,
        *,
        provider_sid: str | None = None,
        browser_hash: str | None = None,
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
        # Retain revoked rows through their expiry: logout needs their browser binding.
        token = secrets.token_urlsafe(32)
        self.db.add(
            AccountSession(
                token_hash=digest(token),
                account_id=account_id,
                browser_hash=browser_hash,
                provider_sid_hash=sid_hash,
                csrf_token=secrets.token_urlsafe(32),
                last_seen_at=now,
                expires_at=now + timedelta(hours=12),
            )
        )
        self.db.flush()
        return token

    def authenticate(
        self,
        token: str | None,
        csrf: str | None = None,
        *,
        mutate: bool = False,
        touch: bool = True,
    ) -> tuple[Account, AccountSession]:
        if not token or len(token) > 128:
            raise InvalidToken()
        statement = select(AccountSession).where(AccountSession.token_hash == digest(token))
        if touch:
            statement = statement.with_for_update()
        row = self.db.scalar(statement.execution_options(populate_existing=True))
        now = datetime.now(UTC)
        if (
            row is None
            or row.revoked_at is not None
            or utc(row.expires_at) <= now
            or utc(row.last_seen_at) <= now - timedelta(minutes=30)
        ):
            raise InvalidToken()
        account = self.db.get(Account, row.account_id, populate_existing=True)
        if account is None or account.disabled:
            raise InvalidToken()
        if mutate and (not csrf or not secrets.compare_digest(row.csrf_token, csrf)):
            raise Forbidden("Refresh the page and retry (CSRF validation failed)")
        if touch:
            row.last_seen_at = now
            self.db.flush()
        return account, row

    def revoke(self, token: str) -> None:
        self.db.execute(
            update(AccountSession)
            .where(AccountSession.token_hash == digest(token))
            .values(revoked_at=datetime.now(UTC))
        )

    def begin_login(
        self, browser_token: str, state: str, nonce: str, verifier: str, previous: str | None
    ) -> None:
        """Linearize a fresh attempt before any provider I/O. No authorization is granted."""
        prior = self.db.get(AccountSession, digest(previous)) if previous else None
        if prior is not None:
            account = self.db.get(Account, prior.account_id)
            assert account is not None
            lock_identity(self.db, account.issuer, account.subject)
            prior = self.db.get(AccountSession, digest(previous or ""), populate_existing=True)
        browser_hash = digest(browser_token)
        self.db.execute(
            insert(BrowserLogin)
            .values(browser_hash=browser_hash, generation=0)
            .on_conflict_do_nothing()
        )
        hashes = {browser_hash}
        if prior is not None and prior.browser_hash:
            hashes.add(prior.browser_hash)
        browsers = list(
            self.db.scalars(
                select(BrowserLogin)
                .where(BrowserLogin.browser_hash.in_(hashes))
                .order_by(BrowserLogin.browser_hash)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        browser = next(row for row in browsers if row.browser_hash == browser_hash)
        # A replaced/missing browser cookie must not leave its older callbacks live.
        for old in browsers:
            if old.browser_hash != browser_hash:
                old.generation += 1
        browser.generation += 1
        if prior is not None:
            # Rotation/logout retains this binding even after the session is revoked.
            prior.browser_hash = browser_hash
        now = datetime.now(UTC)
        expired = select(LoginAttempt.state_hash).where(LoginAttempt.expires_at <= now).limit(100)
        self.db.execute(delete(LoginAttempt).where(LoginAttempt.state_hash.in_(expired)))
        self.db.execute(delete(LoginAttempt).where(LoginAttempt.browser_hash == browser_hash))
        count = self.db.scalar(select(func.count()).select_from(LoginAttempt))
        if count is not None and count >= 1000:
            raise MosaiqueError(ErrorCode.RATE_LIMITED, "Too many sign-in attempts. Retry shortly.")
        login_generation = self.db.scalar(LOGIN_GENERATION.next_value())
        assert login_generation is not None
        self.db.add(
            LoginAttempt(
                state_hash=digest(state),
                browser_hash=browser_hash,
                browser_generation=browser.generation,
                login_generation=login_generation,
                nonce=nonce,
                verifier=verifier,
                expires_at=now + timedelta(minutes=10),
            )
        )
        self.db.flush()

    def complete_login(
        self,
        ticket: LoginTicket,
        *,
        issuer: str,
        subject: str,
        email: str,
        email_verified: bool,
        initial_name: str,
        provider_sid: str,
        previous: str | None,
    ) -> str:
        """Check durable cancellation and issue under the same identity/browser locks."""
        account_id = resolve_account(
            self.db,
            issuer=issuer,
            subject=subject,
            email=email,
            email_verified=email_verified,
            initial_name=initial_name,
        )
        browser = self.db.scalar(
            select(BrowserLogin)
            .where(BrowserLogin.browser_hash == ticket.browser_hash)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        account = self.db.get(Account, account_id, populate_existing=True)
        assert account is not None
        if (
            browser is None
            or browser.generation != ticket.browser_generation
            or ticket.login_generation < account.login_generation
            or utc(ticket.expires_at) <= datetime.now(UTC)
        ):
            raise InvalidToken("Sign-in was cancelled. Start a new login.")
        return self.issue(
            account_id, previous, provider_sid=provider_sid, browser_hash=ticket.browser_hash
        )

    def logout(self, account_id: str, token: str, *, all_sessions: bool) -> None:
        """Cancel pending browser logins, including callbacks already in token exchange."""
        account = self.db.get(Account, account_id, populate_existing=True)
        assert account is not None
        lock_identity(self.db, account.issuer, account.subject)
        account = self.db.get(Account, account_id, populate_existing=True)
        assert account is not None
        row = self.db.get(AccountSession, digest(token), populate_existing=True)
        if row is None or row.account_id != account_id:
            raise InvalidToken()
        now = datetime.now(UTC)
        if row.browser_hash:
            browser = self.db.scalar(
                select(BrowserLogin)
                .where(BrowserLogin.browser_hash == row.browser_hash)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert browser is not None
            browser.generation += 1
            self.db.execute(
                update(AccountSession)
                .where(AccountSession.browser_hash == browser.browser_hash)
                .values(revoked_at=now)
            )
        else:
            row.revoked_at = now
        if all_sessions:
            # DB sequence orders anonymous attempts against account-wide logout:
            # the provider identity need not have been known when they started.
            generation = self.db.scalar(LOGIN_GENERATION.next_value())
            assert generation is not None
            account.login_generation = generation
            self.db.execute(
                update(AccountSession)
                .where(AccountSession.account_id == account_id)
                .values(revoked_at=now)
            )
        self.db.flush()
