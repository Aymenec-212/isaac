"""Meeting routes (tech spec 6).

Slice 0 ships create, list, and read. Join, end, transcript, and outputs arrive
in Slice 1 against this same router.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from mosaique.app.api.dependencies import PrincipalDep, SessionDep, SettingsDep
from mosaique.app.api.schemas import (
    CreateMeetingRequest,
    CreateMeetingResponse,
    ErrorEnvelope,
    MeetingDetailView,
    MeetingListResponse,
    MeetingView,
)
from mosaique.app.auth.authorize import authorize_meeting_access
from mosaique.app.auth.tokens import hash_token, issue_host_token, new_invite_token
from mosaique.domain.errors import NotFound
from mosaique.domain.ids import is_valid_id
from mosaique.domain.state import MeetingState, open_room
from mosaique.observability.logging import get_logger
from mosaique.persistence.repositories.meetings import MeetingRepository

# Documented on every route so the error envelope is part of the published
# contract and lands in the generated frontend client (tech spec 6).
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "Missing or invalid token"},
    403: {"model": ErrorEnvelope, "description": "Not permitted"},
    404: {"model": ErrorEnvelope, "description": "Meeting not found"},
    500: {"model": ErrorEnvelope, "description": "Internal error"},
}

router = APIRouter(prefix="/meetings", tags=["meetings"], responses=ERROR_RESPONSES)
log = get_logger(__name__)


@router.post("", response_model=CreateMeetingResponse, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    body: CreateMeetingRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> CreateMeetingResponse:
    """Create a meeting and return the host token plus the invite link."""
    repo = MeetingRepository(session, principal.organization_id)
    invite_token = new_invite_token()
    meeting = await repo.create(
        host_user_id=principal.subject_id,
        title=body.title,
        state=open_room(MeetingState.CREATED),
        invite_token_hash=hash_token(invite_token),
    )
    log.info("meeting_created", meeting_id=meeting.id, state=meeting.state)
    return CreateMeetingResponse(
        meeting=MeetingView.model_validate(meeting),
        host_token=issue_host_token(
            user_id=principal.subject_id,
            organization_id=principal.organization_id,
            secret=settings.token_secret,
            ttl_hours=settings.host_token_ttl_hours,
        ),
        invite_url=f"/join/{meeting.id}?t={invite_token}",
    )


@router.get("", response_model=MeetingListResponse)
async def list_meetings(principal: PrincipalDep, session: SessionDep) -> MeetingListResponse:
    """Meetings for the caller's organization, newest first."""
    repo = MeetingRepository(session, principal.organization_id)
    meetings = await repo.list()
    return MeetingListResponse(meetings=[MeetingView.model_validate(m) for m in meetings])


@router.get("/{meeting_id}", response_model=MeetingDetailView)
async def get_meeting(
    meeting_id: str, principal: PrincipalDep, session: SessionDep
) -> MeetingDetailView:
    if not is_valid_id(meeting_id):
        raise NotFound()
    repo = MeetingRepository(session, principal.organization_id)
    meeting = authorize_meeting_access(principal, await repo.get(meeting_id))
    return MeetingDetailView.model_validate(meeting)
