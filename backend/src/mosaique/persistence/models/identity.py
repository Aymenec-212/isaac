"""Additive M1 identity tables. Legacy users and meeting credentials are unrelated."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from mosaique.persistence.models.base import Base, created_at_col, ulid_pk


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_accounts_identity"),)

    id: Mapped[str] = ulid_pk()
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
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
