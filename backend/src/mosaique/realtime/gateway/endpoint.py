"""The WebSocket endpoint (tech spec 7).

Responsibilities stop at the seam: authenticate, validate frames, and submit
`IngressEvent`s. It holds no transcript state and makes no ASR call.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from mosaique.app.auth.tokens import verify_token
from mosaique.config.settings import get_settings
from mosaique.domain.errors import InvalidToken
from mosaique.domain.ids import new_id
from mosaique.domain.state import MeetingState, accepts_audio
from mosaique.observability.logging import get_logger
from mosaique.observability.metrics import METRICS
from mosaique.persistence.engine import session_scope
from mosaique.persistence.repositories.meetings import MeetingRepository
from mosaique.persistence.repositories.transcript import ParticipantRepository
from mosaique.realtime.gateway.ingress import BrowserWebSocketIngress
from mosaique.realtime.ingress import (
    MeetingRef,
    ParticipantAudioState,
    ParticipantJoined,
    ParticipantLeft,
)
from mosaique.realtime.ingress.interfaces import IngressAudioFrame, IngressEvent
from mosaique.realtime.protocol.frames import FrameRejection, InvalidFrame, decode_frame
from mosaique.realtime.protocol.messages import ErrorMessage, Hello, HelloOk, Ping, Pong
from mosaique.realtime.runtime_state import get_registry, is_draining

log = get_logger(__name__)
router = APIRouter()

# Tech spec 7.4: ping every 10 s; a socket with no pong and no frame for 30 s
# is dead. Both are transport concerns and stay on this side of the seam — the
# runtime is told the stream was lost, never why.
PING_INTERVAL_S = 10.0
STALE_AFTER_S = 30.0


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _submit(
    ingress: BrowserWebSocketIngress, event: IngressEvent, websocket: WebSocket
) -> bool:
    if ingress.submit(event):
        return True
    try:
        async with asyncio.timeout(1.0):
            await websocket.send_json(
                ErrorMessage(
                    code="INGRESS_UNAVAILABLE",
                    message="Audio was not accepted; reconnect to resume capture.",
                    fatal=False,
                ).model_dump()
            )
            await websocket.close(code=1013)
    except Exception:
        pass
    return False


async def _keepalive(websocket: WebSocket, liveness: _Liveness) -> None:
    """Ping on a timer and hang up on a socket that has gone quiet.

    A dropped TCP connection is often not reported to the application at all —
    a suspended tab is the common case — so silence, not an error, is what says
    the client is gone. Closing here is what starts the reconnect grace, since
    the runtime only ever learns that the transport ended.
    """
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL_S)
            if liveness.silent_for() > STALE_AFTER_S:
                log.info("ws_stale", silent_s=round(liveness.silent_for(), 1))
                await websocket.close(code=1001)
                return
            await websocket.send_json(Ping(t=_now_ms()).model_dump())
    except asyncio.CancelledError:
        raise
    except Exception:
        # The socket died under us; the frame loop will notice and clean up.
        return


class _Liveness:
    """Last time this socket proved it was still there."""

    def __init__(self) -> None:
        self._last = time.monotonic()

    def seen(self) -> None:
        self._last = time.monotonic()

    def silent_for(self) -> float:
        return time.monotonic() - self._last


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_socket(websocket: WebSocket, meeting_id: str) -> None:
    await websocket.accept()
    if is_draining():
        # A deploy is in progress. 1012 is "service restart": clients reconnect
        # on it rather than treating it as fatal (tech spec 14.1).
        await websocket.close(code=1012)
        return
    settings = get_settings()
    participant_id: str | None = None
    audio_session_id = new_id()
    keepalive: asyncio.Task[None] | None = None

    try:
        # ---- hello: no audio is accepted before hello.ok (tech spec 13.1) ----
        try:
            hello = Hello.model_validate(await websocket.receive_json())
            principal = verify_token(hello.session_token, secret=settings.token_secret)
        except (ValidationError, InvalidToken, KeyError):
            await websocket.send_json(
                ErrorMessage(
                    code="AUTH_INVALID_TOKEN", message="Invalid session token", fatal=True
                ).model_dump()
            )
            await websocket.close(code=1008)
            return

        if principal.meeting_id != meeting_id:
            await websocket.send_json(
                ErrorMessage(
                    code="AUTH_FORBIDDEN", message="Token is for another meeting", fatal=True
                ).model_dump()
            )
            await websocket.close(code=1008)
            return

        async with session_scope() as db:
            meeting = await MeetingRepository(db, principal.organization_id).get(meeting_id)
            if meeting is None:
                await websocket.close(code=1008)
                return
            participant = await ParticipantRepository(db, principal.organization_id).get(
                principal.subject_id
            )
            if participant is None:
                await websocket.close(code=1008)
                return
            state = MeetingState(meeting.state)
            if not accepts_audio(state):
                await websocket.send_json(
                    ErrorMessage(
                        code="MEETING_NOT_LIVE",
                        message="Meeting is not accepting audio",
                        fatal=True,
                    ).model_dump()
                )
                await websocket.close(code=1000)
                return
            # ADR-11: the meeting clock starts here, on the server.
            if meeting.started_at is None:
                from datetime import UTC, datetime

                meeting.started_at = datetime.now(UTC)
                meeting.state = str(MeetingState.LIVE)
            started_at_ms = int(meeting.started_at.timestamp() * 1000)
            display_name = participant.display_name
            organization_id = meeting.organization_id

        participant_id = principal.subject_id
        registry = get_registry()

        previous = await registry.broadcaster.register(meeting_id, participant_id, websocket)
        if previous is not None:
            # Tech spec 7.4: a second tab must not double the audio. Telling the
            # first socket is not enough — a client that ignores the error would
            # keep streaming — so it is closed here rather than asked to leave.
            with contextlib.suppress(Exception):
                await previous.send_json(
                    ErrorMessage(
                        code="SESSION_REPLACED", message="Meeting opened elsewhere", fatal=True
                    ).model_dump()
                )
            with contextlib.suppress(Exception):
                await previous.close(code=1000)

        runtime = await registry.ensure(
            MeetingRef(meeting_id=meeting_id, organization_id=organization_id),
            started_at_ms,
        )
        ingress = registry.ingress_for(meeting_id)
        assert ingress is not None

        # Tech spec 7.4: a `hello` inside the reconnect grace resumes the stream
        # in place. The runtime owns that decision; the gateway only reports it,
        # and carries the sequence forward so a replayed client buffer is still
        # checked for duplicates.
        resume = runtime.resume_info(participant_id)

        if not await _submit(
            ingress,
            ParticipantJoined(
                participant_id=participant_id,
                display_name=display_name,
                audio_session_id=audio_session_id,
            ),
            websocket,
        ):
            return
        await websocket.send_json(
            HelloOk(
                participant_id=participant_id,
                display_name=display_name,
                meeting_state=str(MeetingState.LIVE),
                meeting_started_at=started_at_ms,
                resume=resume.resuming,
            ).model_dump()
        )
        log.info(
            "ws_connected",
            meeting_id=meeting_id,
            participant_id=participant_id,
            resume=resume.resuming,
        )

        # ---- frame loop ----------------------------------------------------
        last_seq = resume.last_sequence
        liveness = _Liveness()
        keepalive = asyncio.create_task(_keepalive(websocket, liveness))
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            liveness.seen()

            if (raw := message.get("bytes")) is not None:
                try:
                    frame = decode_frame(raw)
                except InvalidFrame as exc:
                    METRICS.frame_rejected(exc.reason)
                    await websocket.send_json(
                        ErrorMessage(
                            code="AUDIO_INVALID_FRAME", message=str(exc), fatal=False
                        ).model_dump()
                    )
                    continue

                if frame.sequence <= last_seq:
                    METRICS.frame_rejected(FrameRejection.DUPLICATE_SEQUENCE)
                    continue
                last_seq = frame.sequence
                METRICS.frame_received()
                if not await _submit(
                    ingress,
                    IngressAudioFrame(
                        participant_id=participant_id,
                        audio_session_id=audio_session_id,
                        seq=frame.sequence,
                        pcm=frame.pcm,
                        capture_ms=frame.capture_ms,
                    ),
                    websocket,
                ):
                    break
                continue

            if (text := message.get("text")) is not None:
                payload = json.loads(text)
                kind = payload.get("type")
                if kind == "ping":
                    await websocket.send_json(Pong(t=payload.get("t", _now_ms())).model_dump())
                elif kind == "pong":
                    pass  # `liveness.seen()` above already recorded it
                elif kind in ("audio.pause", "audio.resume"):  # noqa: SIM102
                    # Tech spec 7.1: the session stays, the server just stops
                    # expecting frames. Without this a mute is indistinguishable
                    # from a stalled network and the status bar cries wolf.
                    if not await _submit(
                        ingress,
                        ParticipantAudioState(
                            participant_id=participant_id,
                            paused=kind == "audio.pause",
                        ),
                        websocket,
                    ):
                        break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.error("ws_failed", error_type=type(exc).__name__)
    finally:
        if keepalive is not None:
            keepalive.cancel()
        if participant_id is not None:
            registry = get_registry()
            await registry.broadcaster.unregister(meeting_id, participant_id)
            ingress = registry.ingress_for(meeting_id)
            if ingress is not None and not ingress.submit(
                ParticipantLeft(participant_id=participant_id)
            ):
                log.warning("ingress_leave_rejected", participant_id=participant_id)
            log.info("ws_disconnected", meeting_id=meeting_id, participant_id=participant_id)
