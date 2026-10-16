"""Public enterprise response contract; persistence models stay private."""

from typing import Literal

from pydantic import BaseModel

Role = Literal["owner", "admin", "member"]


class AccountView(BaseModel):
    id: str
    email: str
    email_verified: bool
    display_name: str
    csrf_token: str


class WorkspaceView(BaseModel):
    id: str
    name: str
    role: Role


class MemberView(BaseModel):
    id: str
    email: str
    display_name: str
    role: Role
    disabled: bool


class EnterpriseMeetingView(BaseModel):
    id: str
    organization_id: str
    title: str
    state: str
    organizer_account_id: str
    created_at: str


class InvitationView(BaseModel):
    id: str
    email: str
    expires_at: str


class InvitationToken(BaseModel):
    token: str
