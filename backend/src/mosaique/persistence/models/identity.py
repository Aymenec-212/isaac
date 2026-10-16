"""Additive M1 identity tables. Legacy users and meeting credentials are unrelated."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Sequence,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from mosaique.persistence.models.base import Base, created_at_col, ulid_pk

LOGIN_GENERATION = Sequence("identity_login_generation", metadata=Base.metadata)


class BrowserLogin(Base):
    __tablename__ = "browser_logins"
    browser_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_accounts_identity"),)

    id: Mapped[str] = ulid_pk()
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    login_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (CheckConstraint("role IN ('owner', 'admin', 'member')", name="role_valid"),)

    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(8), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class Invitation(Base):
    __tablename__ = "workspace_invitations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "invited_by"],
            ["memberships.organization_id", "memberships.account_id"],
            name="fk_workspace_invitations_inviter_membership",
        ),
    )

    id: Mapped[str] = ulid_pk()
    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_by: Mapped[str] = mapped_column(String(26), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class MeetingAccess(Base):
    __tablename__ = "meeting_access"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "meeting_id"],
            ["meetings.organization_id", "meetings.id"],
            name="fk_meeting_access_meeting",
        ),
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["memberships.organization_id", "memberships.account_id"],
            name="fk_meeting_access_membership",
        ),
    )
    organization_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    created_at: Mapped[datetime] = created_at_col()


class AccountSession(Base):
    __tablename__ = "account_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    browser_hash: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("browser_logins.browser_hash"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_sid_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LoginAttempt(Base):
    """Short-lived OIDC state, nonce and PKCE verifier never sent in browser cookies."""

    __tablename__ = "login_attempts"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    browser_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    login_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkspaceAudit(Base):
    __tablename__ = "workspace_audit"
    id: Mapped[str] = ulid_pk()
    organization_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("organizations.id"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(26), ForeignKey("accounts.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(26), nullable=False)
    context_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class RevokedProviderSession(Base):
    """Fences callbacks even when logout arrives before an account's first login."""

    __tablename__ = "revoked_provider_sessions"
    identity_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    sid_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = created_at_col()
