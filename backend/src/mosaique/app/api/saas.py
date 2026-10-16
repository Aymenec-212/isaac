"""Enterprise HTTP boundary. Authority comes exclusively from opaque server sessions."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from mosaique.app.api.dependencies import SessionDep, SettingsDep
from mosaique.app.api.saas_schemas import (
    AccountView,
    EnterpriseMeetingView,
    InvitationToken,
    InvitationView,
    MemberView,
    WorkspaceView,
)
from mosaique.domain.errors import Forbidden
from mosaique.identity.sessions import Sessions
from mosaique.meetings.service import Meetings
from mosaique.persistence.models.identity import Account, Membership
from mosaique.workspaces.service import Workspaces

router = APIRouter(prefix="/saas", tags=["enterprise"])
COOKIE = "mosaique_session"


async def current_account(request: Request, db: SessionDep, settings: SettingsDep) -> str:
    mutate = request.method not in ("GET", "HEAD", "OPTIONS")
    if mutate and request.headers.get("origin") != settings.public_origin:
        raise Forbidden("Request origin not allowed")
    account, session = await db.run_sync(
        lambda s: Sessions(s).authenticate(
            request.cookies.get(COOKIE),
            request.headers.get("x-csrf-token"),
            mutate=mutate,
            touch=request.url.path not in ("/saas/logout", "/saas/logout-all"),
        )
    )
    request.state.account_session = session
    return account.id


Actor = Annotated[str, Depends(current_account)]


class Name(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class Profile(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class Invite(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class Accept(BaseModel):
    token: str = Field(min_length=1, max_length=128)


class RoleUpdate(BaseModel):
    role: Literal["owner", "admin", "member"] | None


class NewMeeting(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class Grant(BaseModel):
    allow: bool


def org_view(org: Any, role: str) -> dict[str, str]:
    return {"id": org.id, "name": org.name, "role": role}


def meeting_view(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "title": row.title,
        "state": row.state,
        "organizer_account_id": row.organizer_account_id,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/me", response_model=AccountView)
async def me(actor: Actor, request: Request, db: SessionDep) -> dict[str, Any]:
    account = await db.get(Account, actor)
    assert account is not None
    return {
        "id": account.id,
        "email": account.email,
        "email_verified": account.email_verified,
        "display_name": account.display_name,
        "csrf_token": request.state.account_session.csrf_token,
    }


@router.patch("/me")
async def profile(body: Profile, actor: Actor, db: SessionDep) -> dict[str, str]:
    from mosaique.identity.accounts import update_profile

    name = await db.run_sync(lambda s: update_profile(s, actor, body.display_name))
    return {"display_name": name}


@router.post("/logout")
async def logout(
    actor: Actor, request: Request, response: Response, db: SessionDep
) -> dict[str, bool]:
    await db.run_sync(
        lambda s: Sessions(s).logout(actor, request.cookies[COOKIE], all_sessions=False)
    )
    response.delete_cookie(COOKIE, path="/")
    return {"signed_out": True}


@router.get("/workspaces", response_model=list[WorkspaceView])
async def workspaces(actor: Actor, db: SessionDep) -> list[dict[str, str]]:
    return await db.run_sync(
        lambda s: [
            org_view(org, Workspaces(s).authorize(actor, org.id).role)
            for org in Workspaces(s).list(actor)
        ]
    )


@router.post("/workspaces", status_code=201, response_model=WorkspaceView)
async def create_workspace(body: Name, actor: Actor, db: SessionDep) -> dict[str, str]:
    return await db.run_sync(lambda s: org_view(Workspaces(s).create(actor, body.name), "owner"))


@router.patch("/workspaces/{org}")
async def rename_workspace(org: str, body: Name, actor: Actor, db: SessionDep) -> dict[str, bool]:
    await db.run_sync(lambda s: Workspaces(s).rename(actor, org, body.name))
    return {"saved": True}


@router.get("/workspaces/{org}/members", response_model=list[MemberView])
async def members(org: str, actor: Actor, db: SessionDep) -> list[dict[str, Any]]:
    def read(s: Any) -> list[dict[str, Any]]:
        Workspaces(s).authorize(actor, org)
        rows = s.execute(
            select(Account, Membership)
            .join(Membership, Membership.account_id == Account.id)
            .where(Membership.organization_id == org, Membership.revoked_at.is_(None))
        )
        return [
            {
                "id": a.id,
                "display_name": a.display_name,
                "email": a.email,
                "role": m.role,
                "disabled": a.disabled,
            }
            for a, m in rows
        ]

    return await db.run_sync(read)


@router.patch("/workspaces/{org}/members/{target}")
async def change_member(
    org: str, target: str, body: RoleUpdate, actor: Actor, db: SessionDep
) -> dict[str, bool]:
    await db.run_sync(lambda s: Workspaces(s).change_member(actor, org, target, role=body.role))
    return {"saved": True}


@router.post("/workspaces/{org}/invitations", status_code=201, response_model=InvitationToken)
async def invite(org: str, body: Invite, actor: Actor, db: SessionDep) -> dict[str, str]:
    token = await db.run_sync(lambda s: Workspaces(s).invite(actor, org, body.email))
    return {"token": token}


@router.post("/invitations/accept", response_model=WorkspaceView)
async def accept(body: Accept, actor: Actor, db: SessionDep) -> dict[str, str]:
    def redeem(s: Any) -> dict[str, str]:
        org = Workspaces(s).accept(actor, body.token)
        return org_view(org, Workspaces(s).authorize(actor, org.id).role)

    return await db.run_sync(redeem)


@router.get("/workspaces/{org}/meetings", response_model=list[EnterpriseMeetingView])
async def meetings(org: str, actor: Actor, db: SessionDep) -> list[dict[str, Any]]:
    return await db.run_sync(lambda s: [meeting_view(m) for m in Meetings(s).list(actor, org)])


@router.post("/workspaces/{org}/meetings", status_code=201, response_model=EnterpriseMeetingView)
async def create_meeting(
    org: str, body: NewMeeting, actor: Actor, db: SessionDep
) -> dict[str, Any]:
    return await db.run_sync(lambda s: meeting_view(Meetings(s).create(actor, org, body.title)))


@router.get("/workspaces/{org}/meetings/{meeting_id}", response_model=EnterpriseMeetingView)
async def meeting(org: str, meeting_id: str, actor: Actor, db: SessionDep) -> dict[str, Any]:
    return await db.run_sync(lambda s: meeting_view(Meetings(s).get(actor, org, meeting_id)))


@router.put("/workspaces/{org}/meetings/{meeting_id}/access/{target}")
async def grant(
    org: str, meeting_id: str, target: str, body: Grant, actor: Actor, db: SessionDep
) -> dict[str, bool]:
    await db.run_sync(lambda s: Meetings(s).grant(actor, org, meeting_id, target, allow=body.allow))
    return {"saved": True}


@router.get("/workspaces/{org}/invitations", response_model=list[InvitationView])
async def invitations(org: str, actor: Actor, db: SessionDep) -> list[dict[str, str]]:
    return await db.run_sync(
        lambda s: [
            {"id": i.id, "email": i.email, "expires_at": i.expires_at.isoformat()}
            for i in Workspaces(s).invitations(actor, org)
        ]
    )


@router.delete("/workspaces/{org}/invitations/{invitation_id}")
async def revoke_invitation(
    org: str, invitation_id: str, actor: Actor, db: SessionDep
) -> dict[str, bool]:
    await db.run_sync(lambda s: Workspaces(s).revoke_invitation(actor, org, invitation_id))
    return {"revoked": True}


@router.post("/session/activity")
async def activity(actor: Actor) -> dict[str, bool]:
    # Authentication advances idle time; the fixed absolute deadline never moves.
    return {"active": True}


@router.post("/logout-all")
async def logout_all(
    actor: Actor, request: Request, response: Response, db: SessionDep
) -> dict[str, bool]:
    await db.run_sync(
        lambda s: Sessions(s).logout(actor, request.cookies[COOKIE], all_sessions=True)
    )
    response.delete_cookie(COOKIE, path="/")
    return {"signed_out": True}


@router.get("/workspaces/{org}/audit")
async def audit(org: str, actor: Actor, db: SessionDep) -> list[dict[str, str]]:
    from mosaique.persistence.models.identity import WorkspaceAudit

    def read(s: Any) -> list[dict[str, str]]:
        Workspaces(s).authorize_manager(actor, org)
        rows = s.scalars(
            select(WorkspaceAudit)
            .where(WorkspaceAudit.organization_id == org)
            .order_by(WorkspaceAudit.created_at.desc(), WorkspaceAudit.id.desc())
            .limit(100)
        )
        return [
            {
                "id": r.id,
                "actor_id": r.actor_id,
                "action": r.action,
                "target_id": r.target_id,
                "context_id": r.context_id or "",
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    return await db.run_sync(read)


@router.get("/workspaces/{org}/meetings/{meeting_id}/access")
async def meeting_access(org: str, meeting_id: str, actor: Actor, db: SessionDep) -> list[str]:
    return await db.run_sync(lambda s: Meetings(s).access(actor, org, meeting_id))


@router.post("/workspaces/{org}/meetings/{meeting_id}/restore-organizer")
async def restore_organizer(
    org: str, meeting_id: str, actor: Actor, db: SessionDep
) -> dict[str, bool]:
    await db.run_sync(lambda s: Meetings(s).restore_organizer(actor, org, meeting_id))
    return {"restored": True}
