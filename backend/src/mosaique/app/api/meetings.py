"""Meeting routes (tech spec 6).

Slice 0 ships create, list, and read. Join, end, transcript, and outputs arrive
in Slice 1 against this same router.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from mosaique.app.api.dependencies import PrincipalDep, SessionDep, SettingsDep
from mosaique.app.api.ranges import UnsatisfiableRange, parse_range
from mosaique.app.api.schemas import (
    ActionItemView,
    AudioSessionView,
    CreateMeetingRequest,
    CreateMeetingResponse,
    EndMeetingResponse,
    ErrorEnvelope,
    EvidenceItem,
    JoinRequest,
    JoinResponse,
    MeetingDetailView,
    MeetingListResponse,
    MeetingView,
    OutputsResponse,
    ParticipantView,
    SegmentView,
    TranscriptResponse,
)
from mosaique.app.auth.authorize import authorize_meeting_access, require_host
from mosaique.app.auth.tokens import (
    hash_token,
    issue_host_token,
    issue_session_token,
    new_invite_token,
)
from mosaique.domain.errors import ErrorCode, InvalidToken, MosaiqueError, NotFound
from mosaique.domain.ids import is_valid_id
from mosaique.domain.state import InvalidTransition, MeetingState, end, open_room
from mosaique.jobs import JOB_KIND, PROCESSOR_VERSION
from mosaique.observability.logging import get_logger
from mosaique.observability.metrics import METRICS
from mosaique.persistence.models import AudioSession, Meeting
from mosaique.persistence.repositories.meetings import MeetingRepository
from mosaique.persistence.repositories.transcript import (
    AudioSessionRepository,
    JobRepository,
    OutputsRepository,
    ParticipantRepository,
    SegmentRepository,
)
from mosaique.realtime.protocol.messages import MeetingStateMessage
from mosaique.realtime.runtime_state import get_registry

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


@router.post("/{meeting_id}/join", response_model=JoinResponse)
async def join_meeting(
    meeting_id: str,
    body: JoinRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> JoinResponse:
    """Exchange an invite token for a session token (tech spec 13.1).

    The only unauthenticated route. The invite token is compared against its
    stored hash; it is never held in plain text on the server.
    """
    if not is_valid_id(meeting_id):
        raise NotFound()
    stmt = select(Meeting).where(Meeting.id == meeting_id)
    meeting = (await session.execute(stmt)).scalar_one_or_none()
    if meeting is None:
        raise NotFound()
    if meeting.invite_token_hash != hash_token(body.invite_token):
        raise InvalidToken("Invite link is not valid for this meeting")
    if MeetingState(meeting.state) not in (MeetingState.JOINABLE, MeetingState.LIVE):
        raise MosaiqueError(ErrorCode.MEETING_NOT_LIVE, "Meeting is not open for joining")

    participant = await ParticipantRepository(session, meeting.organization_id).create(
        meeting_id=meeting.id, display_name=body.display_name, role="guest"
    )
    log.info("participant_joined", meeting_id=meeting.id, participant_id=participant.id)
    return JoinResponse(
        participant=ParticipantView.model_validate(participant),
        session_token=issue_session_token(
            participant_id=participant.id,
            organization_id=meeting.organization_id,
            meeting_id=meeting.id,
            secret=settings.token_secret,
            ttl_hours=settings.host_token_ttl_hours,
        ),
        ws_url=f"/ws/meetings/{meeting.id}",
        meeting=MeetingView.model_validate(meeting),
    )


@router.post("/{meeting_id}/end", response_model=EndMeetingResponse)
async def end_meeting(
    meeting_id: str, principal: PrincipalDep, session: SessionDep
) -> EndMeetingResponse:
    """End a meeting (tech spec 11). Idempotent: calling it twice is a no-op.

    Ordering matters. The drain runs to a durable boundary *before* the meeting
    is marked COMPLETED, so a crash mid-finalization leaves FINALIZING for the
    startup recovery routine rather than a COMPLETED meeting missing segments.
    """
    if not is_valid_id(meeting_id):
        raise NotFound()
    repo = MeetingRepository(session, principal.organization_id)
    meeting = authorize_meeting_access(principal, await repo.get(meeting_id))
    require_host(principal)

    current = MeetingState(meeting.state)
    if current is MeetingState.COMPLETED:
        return EndMeetingResponse(meeting=MeetingView.model_validate(meeting))
    try:
        meeting.state = str(end(current))
    except InvalidTransition as exc:
        raise MosaiqueError(ErrorCode.MEETING_INVALID_TRANSITION, str(exc)) from exc
    await session.flush()
    await session.commit()

    asr_version = await get_registry().finalize(meeting_id)

    meeting.state = str(MeetingState.COMPLETED)
    meeting.transcript_version = 1
    # ADR-13 consequence 3: model, runtime and quantization together, or an
    # MLX-era transcript and a CUDA-era one become indistinguishable and every
    # WER comparison built on them is unsound.
    if asr_version is not None:
        meeting.asr_version = asr_version
    meeting.ended_at = datetime.now(UTC)
    await session.flush()

    created = await JobRepository(session).enqueue(
        kind=JOB_KIND,
        meeting_id=meeting.id,
        organization_id=meeting.organization_id,
        idempotency_key=f"{meeting.id}:1:{PROCESSOR_VERSION}",
        payload={"transcript_version": 1, "processor_version": PROCESSOR_VERSION},
    )
    METRICS.meeting_completed()
    log.info("meeting_completed", meeting_id=meeting.id, job_created=created)

    await get_registry().broadcaster.publish(
        meeting_id, MeetingStateMessage(state=str(MeetingState.COMPLETED)).model_dump()
    )
    return EndMeetingResponse(meeting=MeetingView.model_validate(meeting))


@router.get("/{meeting_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    meeting_id: str, principal: PrincipalDep, session: SessionDep
) -> TranscriptResponse:
    """Final segments in display order. Interim text is never stored (ADR-05)."""
    if not is_valid_id(meeting_id):
        raise NotFound()
    repo = MeetingRepository(session, principal.organization_id)
    meeting = authorize_meeting_access(principal, await repo.get(meeting_id))
    segments = await SegmentRepository(session, principal.organization_id).list_for_meeting(
        meeting_id
    )
    participants = await ParticipantRepository(session, principal.organization_id).list_for_meeting(
        meeting_id
    )
    audio_sessions = await AudioSessionRepository(
        session, principal.organization_id
    ).list_for_meeting(meeting_id)
    return TranscriptResponse(
        meeting_id=meeting.id,
        transcript_version=meeting.transcript_version,
        participants=[ParticipantView.model_validate(p) for p in participants],
        segments=[SegmentView.model_validate(s) for s in segments],
        audio_sessions=[AudioSessionView.model_validate(a) for a in audio_sessions],
    )


@router.get("/{meeting_id}/outputs", response_model=OutputsResponse)
async def get_outputs(
    meeting_id: str, principal: PrincipalDep, session: SessionDep, response: Response
) -> OutputsResponse:
    """Outputs when they exist, otherwise 202 with the job's state."""
    if not is_valid_id(meeting_id):
        raise NotFound()
    repo = MeetingRepository(session, principal.organization_id)
    authorize_meeting_access(principal, await repo.get(meeting_id))

    outputs = await OutputsRepository(session, principal.organization_id).get(meeting_id)
    if outputs is not None:
        return OutputsResponse(
            status="succeeded",
            summary=outputs.summary,
            key_points=list(outputs.key_points or []),
            decisions=[EvidenceItem(**d) for d in (outputs.decisions or [])],
            action_items=[ActionItemView(**a) for a in (outputs.action_items or [])],
            open_questions=[EvidenceItem(**q) for q in (outputs.open_questions or [])],
        )

    job = await JobRepository(session).get_latest_for_meeting(meeting_id)
    if job is not None and job.status == "failed":
        return OutputsResponse(status="failed", error_code="POSTPROCESSING_FAILED")
    response.status_code = status.HTTP_202_ACCEPTED
    return OutputsResponse(status=job.status if job else "pending")


# Canonical audio is headerless PCM, so the browser is told exactly that and
# decodes it with the Web Audio API rather than an <audio> element. Declaring
# it audio/wav would be a lie a media element believes until it fails.
AUDIO_CONTENT_TYPE = "application/octet-stream"


@router.get("/{meeting_id}/audio/{session_id}")
async def get_audio(
    meeting_id: str,
    session_id: str,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> Response:
    """Stored PCM for one audio session, with Range support (tech spec 6, FR-11).

    The review page seeks by timestamp, and `store.py` makes that arithmetic
    rather than a lookup: the file holds silence padding too, so
    `byte_offset = session_ms * BYTES_PER_MS` is exact. This route does not
    need to know that — it answers in bytes and lets the caller do the sum.

    Tenancy is enforced the same way every other read is, and then once more:
    the `AudioSession` row must belong to the meeting named in the path, so a
    valid session id from another meeting in the same organization cannot be
    replayed here.
    """
    if not is_valid_id(meeting_id) or not is_valid_id(session_id):
        raise NotFound()

    repo = MeetingRepository(session, principal.organization_id)
    authorize_meeting_access(principal, await repo.get(meeting_id))

    audio_session = await session.get(AudioSession, session_id)
    if (
        audio_session is None
        or audio_session.organization_id != principal.organization_id
        or audio_session.meeting_id != meeting_id
        or not audio_session.audio_object_key
    ):
        raise NotFound()

    store = get_registry().audio_store
    total = store.size_bytes(audio_session.audio_object_key)
    if total is None:
        # The row exists but the bytes do not: the null store discarded them,
        # or Q3 retention removed them. Not an error in the transcript sense —
        # the meeting is still fully readable without its audio.
        raise NotFound()

    try:
        byte_range = parse_range(request.headers.get("range"), total)
    except UnsatisfiableRange:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{total}"},
        )

    headers = {
        # Without this a browser never issues a second request, so the scrub
        # bar renders but seeking does nothing.
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
    }
    if byte_range is None:
        return StreamingResponse(
            store.read_range(audio_session.audio_object_key, 0, total),
            media_type=AUDIO_CONTENT_TYPE,
            headers={**headers, "Content-Length": str(total)},
        )

    return StreamingResponse(
        store.read_range(audio_session.audio_object_key, byte_range.start, byte_range.length),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=AUDIO_CONTENT_TYPE,
        headers={
            **headers,
            "Content-Range": byte_range.content_range,
            "Content-Length": str(byte_range.length),
        },
    )
