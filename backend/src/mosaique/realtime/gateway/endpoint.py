"""The WebSocket endpoint (tech spec 7).

Responsibilities stop at the seam: authenticate, validate frames, and submit
`IngressEvent`s. It holds no transcript state and makes no ASR call.
"""

from __future__ import annotations

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
from mosaique.realtime.ingress import MeetingRef, ParticipantJoined, ParticipantLeft
from mosaique.realtime.ingress.interfaces import IngressAudioFrame
from mosaique.realtime.protocol.frames import FrameRejection, InvalidFrame, decode_frame
from mosaique.realtime.protocol.messages import ErrorMessage, Hello, HelloOk, Pong
from mosaique.realtime.runtime_state import get_registry

log = get_logger(__name__)
router = APIRouter()


def _now_ms() -> int:
    return int(time.time() * 1000)


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_socket(websocket: WebSocket, meeting_id: str) -> None:
    await websocket.accept()
    settings = get_settings()
    participant_id: str | None = None
    audio_session_id = new_id()

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
            # Tech spec 7.4: a second tab must not double the audio.
            with contextlib.suppress(Exception):
                await previous.send_json(
                    ErrorMessage(
                        code="SESSION_REPLACED", message="Meeting opened elsewhere", fatal=True
                    ).model_dump()
                )

        await registry.ensure(
            MeetingRef(meeting_id=meeting_id, organization_id=organization_id),
            started_at_ms,
        )
        ingress = registry.ingress_for(meeting_id)
        assert ingress is not None

        ingress.submit(
            ParticipantJoined(
                participant_id=participant_id,
                display_name=display_name,
                audio_session_id=audio_session_id,
            )
        )
        await websocket.send_json(
            HelloOk(
                participant_id=participant_id,
                display_name=display_name,
                meeting_state=str(MeetingState.LIVE),
                meeting_started_at=started_at_ms,
            ).model_dump()
        )
        log.info("ws_connected", meeting_id=meeting_id, participant_id=participant_id)

        # ---- frame loop ----------------------------------------------------
        last_seq = -1
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

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
                ingress.submit(
                    IngressAudioFrame(
                        participant_id=participant_id,
                        audio_session_id=audio_session_id,
                        seq=frame.sequence,
                        pcm=frame.pcm,
                    )
                )
                continue

            if (text := message.get("text")) is not None:
                payload = json.loads(text)
                if payload.get("type") == "ping":
                    await websocket.send_json(Pong(t=payload.get("t", _now_ms())).model_dump())
                # audio.pause / audio.resume are accepted and ignored in Slice 1 (R-1).

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.error("ws_failed", error_type=type(exc).__name__)
    finally:
        if participant_id is not None:
            registry = get_registry()
            await registry.broadcaster.unregister(meeting_id, participant_id)
            ingress = registry.ingress_for(meeting_id)
            if ingress is not None:
                ingress.submit(ParticipantLeft(participant_id=participant_id))
            log.info("ws_disconnected", meeting_id=meeting_id, participant_id=participant_id)
