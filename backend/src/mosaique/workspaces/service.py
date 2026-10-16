"""Workspace invariants and persistence, independent of HTTP and identity SDKs.

Caller owns one transaction and must commit/rollback it. Async callers can use
AsyncSession.run_sync. Account IDs MUST come from a validated server session,
never request bodies or legacy bearer claims.
All membership mutations lock the organization first, serializing invitation
redemption, role changes and revocation on PostgreSQL.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from mosaique.domain.errors import ErrorCode, Forbidden, InvalidToken, MosaiqueError, NotFound
from mosaique.domain.ids import new_id
from mosaique.persistence.models import Organization
from mosaique.persistence.models.identity import Account, Invitation, MeetingAccess, Membership
from mosaique.workspaces.audit import record

Role = Literal["owner", "admin", "member"]


def _email(value: str) -> str:
    value = value.strip().casefold()
    if not value or len(value) > 320 or value.count("@") != 1:
        raise MosaiqueError(ErrorCode.VALIDATION_FAILED, "Invalid invitation address")
    return value


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    # SQLite's deterministic tests return naive datetimes; PostgreSQL uses UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class Workspaces:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _account(self, account_id: str) -> Account:
        account = self.db.get(Account, account_id, populate_existing=True)
        if account is None or account.disabled:
            raise InvalidToken()
        return account

    def authorize(self, account_id: str, organization_id: str) -> Membership:
        self._account(account_id)
        membership = self.db.get(Membership, (organization_id, account_id), populate_existing=True)
        if membership is None or membership.revoked_at is not None:
            raise NotFound("Workspace not found")
        return membership

    def lock(self, organization_id: str) -> None:
        org = self.db.scalar(
            select(Organization).where(Organization.id == organization_id).with_for_update()
        )
        if org is None:
            raise NotFound("Workspace not found")

    def authorize_manager(self, account_id: str, organization_id: str) -> Membership:
        member = self.authorize(account_id, organization_id)
        if member.role not in ("owner", "admin"):
            raise Forbidden("Workspace manager required")
        return member

    def create(self, account_id: str, name: str) -> Organization:
        self._account(account_id)
        name = name.strip()
        if not name or len(name) > 200:
            raise MosaiqueError(ErrorCode.VALIDATION_FAILED, "Workspace name is required (max 200)")
        org = Organization(id=new_id(), name=name)
        self.db.add(org)
        self.db.flush()
        self.db.add(Membership(organization_id=org.id, account_id=account_id, role="owner"))
        self.db.flush()
        record(self.db, org.id, account_id, "workspace.created", org.id)
        return org

    def list(self, account_id: str) -> list[Organization]:
        self._account(account_id)
        return list(
            self.db.scalars(
                select(Organization)
                .join(Membership)
                .where(Membership.account_id == account_id, Membership.revoked_at.is_(None))
                .order_by(Organization.id)
            )
        )

    def rename(self, account_id: str, organization_id: str, name: str) -> None:
        self.lock(organization_id)
        self.authorize_manager(account_id, organization_id)
        name = name.strip()
        if not name or len(name) > 200:
            raise MosaiqueError(ErrorCode.VALIDATION_FAILED, "Workspace name is required (max 200)")
        org = self.db.get(Organization, organization_id)
        assert org is not None
        org.name = name
        record(self.db, organization_id, account_id, "workspace.renamed", organization_id)
        self.db.flush()

    def invite(self, account_id: str, organization_id: str, email: str) -> str:
        self.lock(organization_id)
        self.authorize_manager(account_id, organization_id)
        token = secrets.token_urlsafe(32)
        invitation_id = new_id()
        self.db.add(
            Invitation(
                id=invitation_id,
                organization_id=organization_id,
                invited_by=account_id,
                email=_email(email),
                token_hash=_hash(token),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        self.db.flush()
        record(self.db, organization_id, account_id, "invitation.created", invitation_id)
        # Only returned to the inviting caller; no email/provider write here.
        return token

    def accept(self, account_id: str, token: str) -> Organization:
        account = self._account(account_id)
        invite = self.db.scalar(select(Invitation).where(Invitation.token_hash == _hash(token)))
        if invite is None:
            raise NotFound("Invitation unavailable")
        self.lock(invite.organization_id)
        invite = self.db.scalar(
            select(Invitation)
            .where(Invitation.token_hash == _hash(token))
            .execution_options(populate_existing=True)
        )
        if invite is None:
            raise NotFound("Invitation unavailable")
        now = datetime.now(UTC)
        if invite.redeemed_at is not None or _utc(invite.expires_at) <= now:
            raise NotFound("Invitation unavailable")
        if not account.email_verified or _email(account.email) != invite.email:
            raise Forbidden("Sign in with the verified invited address")
        # Losing invitation privileges invalidates outstanding invitations.
        self.authorize_manager(invite.invited_by, invite.organization_id)
        member = self.db.get(
            Membership, (invite.organization_id, account_id), populate_existing=True
        )
        if member is None:
            self.db.add(
                Membership(
                    organization_id=invite.organization_id, account_id=account_id, role="member"
                )
            )
        elif member.revoked_at is not None:
            member.revoked_at = None
            member.role = "member"
        # Redeeming a duplicate invite must never demote an existing owner/admin.
        invite.redeemed_at = now
        record(self.db, invite.organization_id, account_id, "invitation.accepted", invite.id)
        self.db.flush()
        org = self.db.get(Organization, invite.organization_id)
        assert org is not None
        return org

    def change_member(
        self, actor_id: str, organization_id: str, target_id: str, *, role: Role | None
    ) -> None:
        """Owner sets a role or revokes (None), preserving the last active owner."""
        if role not in (None, "owner", "admin", "member"):
            raise MosaiqueError(ErrorCode.VALIDATION_FAILED, "Invalid workspace role")
        self.lock(organization_id)
        actor = self.authorize(actor_id, organization_id)
        if actor.role != "owner":
            raise Forbidden("Workspace owner required")
        target = self.db.get(Membership, (organization_id, target_id), populate_existing=True)
        if target is None or target.revoked_at is not None:
            raise NotFound("Workspace not found")
        account = self.db.get(Account, target_id, populate_existing=True)
        assert account is not None
        if account.disabled and role is not None:
            raise Forbidden("Disabled account cannot receive a role")
        if target.role == "owner" and role != "owner" and not account.disabled:
            owners = self.db.scalar(
                select(func.count())
                .select_from(Membership)
                .join(Account)
                .where(
                    Membership.organization_id == organization_id,
                    Membership.role == "owner",
                    Membership.revoked_at.is_(None),
                    Account.disabled.is_(False),
                )
            )
            if owners == 1:
                raise Forbidden("Cannot remove the last owner")
        if role is None:
            target.revoked_at = datetime.now(UTC)
            self.db.execute(
                delete(MeetingAccess).where(
                    MeetingAccess.organization_id == organization_id,
                    MeetingAccess.account_id == target_id,
                )
            )
            self.db.execute(
                delete(Invitation).where(
                    Invitation.organization_id == organization_id,
                    Invitation.email == _email(account.email),
                    Invitation.redeemed_at.is_(None),
                )
            )
        else:
            target.role = role
        record(self.db, organization_id, actor_id, f"membership.{role or 'revoked'}", target_id)
        if role not in ("owner", "admin"):
            # Old invitations must not revive if the inviter is later restored.
            self.db.execute(
                delete(Invitation).where(
                    Invitation.organization_id == organization_id,
                    Invitation.invited_by == target_id,
                    Invitation.redeemed_at.is_(None),
                )
            )
        self.db.flush()

    def invitations(self, actor: str, org: str) -> Sequence[Invitation]:
        self.authorize_manager(actor, org)
        return list(
            self.db.scalars(
                select(Invitation)
                .where(
                    Invitation.organization_id == org,
                    Invitation.redeemed_at.is_(None),
                    Invitation.expires_at > datetime.now(UTC),
                )
                .order_by(Invitation.created_at.desc())
                .limit(100)
            )
        )

    def revoke_invitation(self, actor: str, org: str, invitation_id: str) -> None:
        self.lock(org)
        self.authorize_manager(actor, org)
        invite = self.db.scalar(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.organization_id == org,
                Invitation.redeemed_at.is_(None),
            )
        )
        if invite is None:
            raise NotFound("Invitation unavailable")
        self.db.delete(invite)
        record(self.db, org, actor, "invitation.revoked", invitation_id)
        self.db.flush()
