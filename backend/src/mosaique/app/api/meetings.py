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
    CorrectSegmentRequest,
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
    SegmentMatchView,
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
from mosaique.persistence.models import AudioSession, Meeting, TranscriptSegment
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
from mosaique.transcript.corrections import (
    effective_participant_id,
    effective_text,
    is_corrected,
)
from mosaique.transcript.search import search

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


def segment_view(segment: TranscriptSegment) -> SegmentView:
    """Present a segment with corrections applied, raw values kept beside it.

    One place decides what "the text of this segment" means. Everything that
    reads a transcript — the review page, `?q=` search, evidence resolution —
    goes through here, so a correction cannot be visible in one of them and
    absent from another.
    """
    return SegmentView(
        id=segment.id,
        participant_id=effective_participant_id(segment),
        sequence=segment.sequence,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        text=effective_text(segment),
        status=segment.status,
        audio_session_id=segment.audio_session_id,
        # Only populated when there is something to compare against, so their
        # presence is the "this was edited" signal rather than a second flag
        # that could drift out of step with them.
        original_text=segment.text if segment.corrected_text is not None else None,
        original_participant_id=(
            segment.participant_id if segment.corrected_participant_id is not None else None
        ),
        corrected_at=segment.corrected_at if is_corrected(segment) else None,
    )


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
    meeting = authorize_meeting_access(principal, await repo.get(meeting_id, for_update=True))
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

    try:
        asr_version = await get_registry().finalize(meeting_id)
    except Exception:
        meeting.state = str(MeetingState.FAILED)
        await session.commit()
        await get_registry().broadcaster.publish(
            meeting_id, MeetingStateMessage(state=str(MeetingState.FAILED)).model_dump()
        )
        raise MosaiqueError(
            ErrorCode.MEETING_INVALID_TRANSITION, "Finalization did not reach durable completion"
        ) from None

    meeting = authorize_meeting_access(principal, await repo.get(meeting_id, for_update=True))
    if meeting.state == str(MeetingState.COMPLETED):
        return EndMeetingResponse(meeting=MeetingView.model_validate(meeting))
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
    await session.commit()
    METRICS.meeting_completed()
    log.info("meeting_completed", meeting_id=meeting.id, job_created=created)

    await get_registry().broadcaster.publish(
        meeting_id, MeetingStateMessage(state=str(MeetingState.COMPLETED)).model_dump()
    )
    return EndMeetingResponse(meeting=MeetingView.model_validate(meeting))


@router.get("/{meeting_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    meeting_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    q: str | None = None,
) -> TranscriptResponse:
    """Final segments in display order. Interim text is never stored (ADR-05).

    `?q=` filters to segments containing the text (FR-10, tech spec §6). The
    match is accent-insensitive — see `transcript/search.py` for why that is
    worth a deviation from the spec's "ILIKE for now" in a French-first product.

    Filtering happens after the fetch, which costs nothing extra: rendering the
    transcript already loads every segment.
    """
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
    # Search the *presented* segments, not the database rows: since item 7 a
    # corrected segment's visible text differs from its stored one, and matching
    # the stored text would highlight offsets into a string nobody can see.
    visible, matches = search([segment_view(s) for s in segments], q or "")
    return TranscriptResponse(
        meeting_id=meeting.id,
        transcript_version=meeting.transcript_version,
        participants=[ParticipantView.model_validate(p) for p in participants],
        segments=list(visible),
        audio_sessions=[AudioSessionView.model_validate(a) for a in audio_sessions],
        query=q,
        total_segments=len(segments),
        matches=[
            SegmentMatchView(segment_id=m.segment_id, spans=list(m.spans)) for m in matches.values()
        ],
    )


@router.get("/{meeting_id}/outputs", response_model=OutputsResponse)
async def get_outputs(
    meeting_id: str, principal: PrincipalDep, session: SessionDep, response: Response
) -> OutputsResponse:
    """Outputs when they exist, otherwise 202 with the job's state."""
    if not is_valid_id(meeting_id):
        raise NotFound()
    repo = MeetingRepository(session, principal.organization_id)
    meeting = authorize_meeting_access(principal, await repo.get(meeting_id))

    outputs = await OutputsRepository(session, principal.organization_id).get(meeting_id)
    if outputs is not None:
        return OutputsResponse(
            status="succeeded",
            summary=outputs.summary,
            key_points=list(outputs.key_points or []),
            decisions=[EvidenceItem(**d) for d in (outputs.decisions or [])],
            action_items=[ActionItemView(**a) for a in (outputs.action_items or [])],
            open_questions=[EvidenceItem(**q) for q in (outputs.open_questions or [])],
            # The two numbers the review page compares to decide whether what it
            # is showing still describes the transcript underneath it.
            generated_from_transcript_version=outputs.transcript_version,
            current_transcript_version=meeting.transcript_version,
        )

    job = await JobRepository(session).get_latest_for_meeting(meeting_id)
    if job is not None and job.status == "failed":
        return OutputsResponse(
            status="failed",
            error_code="POSTPROCESSING_FAILED",
            current_transcript_version=meeting.transcript_version,
        )
    response.status_code = status.HTTP_202_ACCEPTED
    return OutputsResponse(
        status=job.status if job else "pending",
        current_transcript_version=meeting.transcript_version,
    )


@router.patch("/{meeting_id}/segments/{segment_id}", response_model=SegmentView)
async def correct_segment(
    meeting_id: str,
    segment_id: str,
    body: CorrectSegmentRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> SegmentView:
    """Correct one segment's text or speaker (Slice 6R item 7, Q9).

    **Additive.** `text` and `words` are never written here — the correction
    lands in `corrected_text` / `corrected_participant_id` beside them, so what
    the model produced stays recoverable. That is not tidiness: L-28's shape and
    every WER figure in §8 are claims about the model's output, and an
    overwriting edit would make them unfalsifiable with no way to tell an edit
    from a transcription.

    **Correcting bumps `transcript_version`.** Any outputs already generated
    were derived from the previous one, so the review page can see that they
    describe text that has since changed. It does **not** re-run the summary:
    that is a paid LLM call and Aymen's decision was to mark it for review and
    offer a button, not to spend money on every keystroke.

    Host-only, like ending a meeting. A guest holding a participant token can
    speak into a transcript but not rewrite it.
    """
    if not is_valid_id(meeting_id) or not is_valid_id(segment_id):
        raise NotFound()
    if body.text is None and body.participant_id is None:
        raise MosaiqueError(
            ErrorCode.VALIDATION_FAILED, "a correction must change the text or the speaker"
        )

    repo = MeetingRepository(session, principal.organization_id)
    meeting = authorize_meeting_access(principal, await repo.get(meeting_id))
    require_host(principal)

    segments = SegmentRepository(session, principal.organization_id)
    segment = await segments.get_for_meeting(meeting_id, segment_id)
    if segment is None:
        raise NotFound()

    if body.participant_id is not None:
        # Reattribution has to stay inside this meeting: a segment owned by
        # someone who was never in the room would break the roster the review
        # page renders speakers from.
        roster = await ParticipantRepository(session, principal.organization_id).list_for_meeting(
            meeting_id
        )
        if body.participant_id not in {p.id for p in roster}:
            raise MosaiqueError(
                ErrorCode.VALIDATION_FAILED, "that speaker is not a participant in this meeting"
            )
        segment.corrected_participant_id = body.participant_id

    if body.text is not None:
        segment.corrected_text = body.text.strip()

    segment.corrected_at = datetime.now(UTC)
    # `subject_id` is the user id for a host, which is who this route allows.
    segment.corrected_by = principal.subject_id
    # The transcript is no longer the one the outputs were derived from.
    meeting.transcript_version = (meeting.transcript_version or 1) + 1
    await session.flush()

    log.info(
        "segment_corrected",
        meeting_id=meeting_id,
        segment_id=segment_id,
        transcript_version=meeting.transcript_version,
        text_changed=body.text is not None,
        speaker_changed=body.participant_id is not None,
    )
    return segment_view(segment)


@router.post("/{meeting_id}/outputs/regenerate", response_model=OutputsResponse, status_code=202)
async def regenerate_outputs(
    meeting_id: str, principal: PrincipalDep, session: SessionDep
) -> OutputsResponse:
    """Re-derive the summary from the corrected transcript.

    Explicit, never automatic — one button, pressed by a person who has finished
    editing. Correcting five segments should cost one LLM call, not five.

    The idempotency key carries the transcript version, so pressing this twice
    for the same version enqueues one job, while pressing it after a further
    correction enqueues a new one. The previous outputs row is left alone: it is
    a true record of what was derived from version N, and `GET /outputs` returns
    the newest, so nothing has to be deleted for the right thing to show.
    """
    if not is_valid_id(meeting_id):
        raise NotFound()
    repo = MeetingRepository(session, principal.organization_id)
    meeting = authorize_meeting_access(principal, await repo.get(meeting_id))
    require_host(principal)

    if MeetingState(meeting.state) is not MeetingState.COMPLETED:
        raise MosaiqueError(
            ErrorCode.MEETING_INVALID_TRANSITION,
            "a meeting must be finished before its summary can be regenerated",
        )

    version = meeting.transcript_version or 1
    created = await JobRepository(session).enqueue(
        kind=JOB_KIND,
        meeting_id=meeting.id,
        organization_id=meeting.organization_id,
        idempotency_key=f"{meeting.id}:{version}:{PROCESSOR_VERSION}",
        payload={"transcript_version": version, "processor_version": PROCESSOR_VERSION},
    )
    log.info(
        "outputs_regeneration_requested",
        meeting_id=meeting_id,
        transcript_version=version,
        job_created=created,
    )
    return OutputsResponse(status="pending", current_transcript_version=version)


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
