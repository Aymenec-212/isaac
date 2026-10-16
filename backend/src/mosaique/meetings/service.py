"""Private meeting authorization. Caller owns the transaction, as for workspaces."""

import builtins

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from mosaique.domain.errors import ErrorCode, Forbidden, MosaiqueError, NotFound
from mosaique.domain.ids import new_id
from mosaique.persistence.models import Meeting
from mosaique.persistence.models.identity import Account, MeetingAccess, Membership
from mosaique.workspaces.audit import record
from mosaique.workspaces.service import Workspaces


class Meetings:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.workspaces = Workspaces(db)

    def list(self, actor: str, org: str) -> list[Meeting]:
        self.workspaces.authorize(actor, org)
        access = select(MeetingAccess.meeting_id).where(
            MeetingAccess.organization_id == org, MeetingAccess.account_id == actor
        )
        return list(
            self.db.scalars(
                select(Meeting)
                .where(
                    Meeting.organization_id == org,
                    Meeting.mode == "enterprise",
                    or_(self._organizer(actor), Meeting.id.in_(access)),
                )
                .order_by(Meeting.created_at.desc(), Meeting.id.desc())
                .limit(100)
            )
        )

    @staticmethod
    def _organizer(actor: str) -> ColumnElement[bool]:
        return and_(Meeting.organizer_account_id == actor, Meeting.organizer_revoked_at.is_(None))

    def get(self, actor: str, org: str, meeting_id: str) -> Meeting:
        self.workspaces.authorize(actor, org)
        access = select(MeetingAccess.meeting_id).where(
            MeetingAccess.organization_id == org, MeetingAccess.account_id == actor
        )
        meeting = self.db.scalar(
            select(Meeting).where(
                Meeting.organization_id == org,
                Meeting.id == meeting_id,
                Meeting.mode == "enterprise",
                or_(self._organizer(actor), Meeting.id.in_(access)),
            )
        )
        if meeting is None:
            raise NotFound()
        return meeting

    def _managed(self, actor: str, org: str, meeting_id: str) -> Meeting:
        meeting = self.get(actor, org, meeting_id)
        if (
            self.db.scalar(
                select(Meeting.id).where(Meeting.id == meeting.id, self._organizer(actor))
            )
            is None
        ):
            raise Forbidden("Meeting organizer required")
        return meeting

    def create(self, actor: str, org: str, title: str) -> Meeting:
        self.workspaces.lock(org)
        self.workspaces.authorize(actor, org)
        title = title.strip()
        if not title or len(title) > 200:
            raise MosaiqueError(ErrorCode.VALIDATION_FAILED, "Meeting title required (max 200)")
        row = Meeting(
            id=new_id(),
            organization_id=org,
            organizer_account_id=actor,
            mode="enterprise",
            title=title,
            state="CREATED",
        )
        self.db.add(row)
        self.db.flush()
        record(self.db, org, actor, "meeting.created", row.id)
        return row

    def grant(self, actor: str, org: str, meeting_id: str, target: str, *, allow: bool) -> None:
        self.workspaces.lock(org)
        self._managed(actor, org, meeting_id)
        target_member = self.db.scalar(
            select(Membership)
            .join(Account, Account.id == Membership.account_id)
            .where(
                Membership.organization_id == org,
                Membership.account_id == target,
                Membership.revoked_at.is_(None),
                Account.disabled.is_(False),
            )
        )
        if target_member is None:
            raise NotFound("Workspace member unavailable")
        key = (org, meeting_id, target)
        existing = self.db.get(MeetingAccess, key, populate_existing=True)
        if allow and existing is None:
            self.db.add(
                MeetingAccess(organization_id=org, meeting_id=meeting_id, account_id=target)
            )
        elif not allow and existing is not None:
            self.db.delete(existing)
        record(
            self.db,
            org,
            actor,
            "meeting.access_granted" if allow else "meeting.access_revoked",
            target,
            context_id=meeting_id,
        )
        self.db.flush()

    def access(self, actor: str, org: str, meeting_id: str) -> builtins.list[str]:
        self._managed(actor, org, meeting_id)
        return list(
            self.db.scalars(
                select(MeetingAccess.account_id).where(
                    MeetingAccess.organization_id == org, MeetingAccess.meeting_id == meeting_id
                )
            )
        )

    def restore_organizer(self, actor: str, org: str, meeting_id: str) -> None:
        """Explicit owner-authorized restoration; rejoining alone never restores authority."""
        self.workspaces.lock(org)
        member = self.workspaces.authorize(actor, org)
        if member.role != "owner":
            raise Forbidden("Workspace owner required")
        meeting = self.db.scalar(
            select(Meeting).where(
                Meeting.organization_id == org,
                Meeting.id == meeting_id,
                Meeting.mode == "enterprise",
            )
        )
        if meeting is None:
            raise NotFound()
        target = self.db.scalar(
            select(Membership)
            .join(Account)
            .where(
                Membership.organization_id == org,
                Membership.account_id == meeting.organizer_account_id,
                Membership.revoked_at.is_(None),
                Account.disabled.is_(False),
            )
        )
        if target is None:
            raise NotFound("Workspace member unavailable")
        if meeting.organizer_revoked_at is not None:
            meeting.organizer_revoked_at = None
            record(
                self.db,
                org,
                actor,
                "meeting.organizer_restored",
                target.account_id,
                context_id=meeting.id,
            )
        self.db.flush()
