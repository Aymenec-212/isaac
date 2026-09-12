"""Meeting intelligence job processor (tech spec 12.1).

An in-process asyncio task, not a separate service (blueprint R-5). The module
boundary is kept so splitting it out later is a deployment change, not a
rewrite.

Two invariants worth stating:

* a failed job never touches the transcript or the meeting state;
* `MeetingOutputs` is written only on success, so `Job` is the single owner of
  execution state and the two cannot drift (blueprint X-12).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mosaique.intelligence.prompt import SYSTEM_PROMPT, build_user_prompt
from mosaique.intelligence.provider import LLMProvider
from mosaique.intelligence.schema import (
    MeetingIntelligence,
    OutputValidationError,
    validate_outputs,
)
from mosaique.observability.logging import get_logger
from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import Job, MeetingOutputs
from mosaique.persistence.repositories.transcript import (
    JobRepository,
    OutputsRepository,
    ParticipantRepository,
    SegmentRepository,
)
from mosaique.realtime.ingress.interfaces import Broadcaster
from mosaique.realtime.protocol.messages import OutputsReady

log = get_logger(__name__)

PROCESSOR_VERSION = "summarizer-v1"
JOB_KIND = "meeting_intelligence"
LLM_DEADLINE_S = 60.0
MAX_ATTEMPTS = 3
BACKOFF_S = (30, 120, 480)


class MeetingIntelligenceProcessor:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        poll_interval_s: float = 1.0,
        broadcaster: Broadcaster | None = None,
    ) -> None:
        """`broadcaster` is optional and injected, never reached for.

        Tech spec 12.1 wants `meeting.outputs.ready` sent to whoever is still
        connected when a job finishes. That is a notification, not a result:
        the outputs are already durable and `GET /outputs` is the contract the
        review page actually depends on (§119). Passing the seam in keeps this
        module free of the transport, and passing None keeps every existing
        test constructing it unchanged.
        """
        self._provider = provider
        self._poll_interval_s = poll_interval_s
        self._broadcaster = broadcaster
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def recover_running(self) -> int:
        """Single-process startup only: no live worker may own these claims."""
        async with session_scope() as db:
            jobs = (
                (
                    await db.execute(
                        select(Job)
                        .where(Job.kind == JOB_KIND, Job.status == "running")
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for job in jobs:
                payload = job.payload or {}
                output = (
                    await db.execute(
                        select(MeetingOutputs.id).where(
                            MeetingOutputs.meeting_id == job.meeting_id,
                            MeetingOutputs.organization_id == job.organization_id,
                            MeetingOutputs.transcript_version
                            == int(payload.get("transcript_version", 1)),
                            MeetingOutputs.processor_version
                            == payload.get("processor_version", PROCESSOR_VERSION),
                        )
                    )
                ).scalar_one_or_none()
                if output is not None:
                    job.status = "succeeded"
                    job.last_error = None
                else:
                    job.status = "failed" if job.attempts >= MAX_ATTEMPTS else "pending"
                    job.next_run_at = datetime.now(UTC)
                    job.last_error = "Worker interrupted before durable output"
            return len(jobs)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("job_loop_failed", error_type=type(exc).__name__)
                processed = False
            if not processed:
                await asyncio.sleep(self._poll_interval_s)

    async def run_once(self) -> bool:
        """Claim and run at most one job. Returns True when one was claimed."""
        async with session_scope() as db:
            job = await JobRepository(db).claim_one()
            if job is None:
                return False
            job_id, meeting_id, organization_id = job.id, job.meeting_id, job.organization_id
            attempts = job.attempts
            payload = dict(job.payload or {})

        try:
            await self._run_job(meeting_id, organization_id, payload)
        except Exception as exc:
            await self._record_failure(job_id, attempts, exc)
            return True

        async with session_scope() as db:
            claimed = await db.get(Job, job_id)
            if claimed is not None:
                claimed.status = "succeeded"
                claimed.last_error = None
        log.info("job_succeeded", meeting_id=meeting_id, job_id=job_id)
        await self._announce_ready(meeting_id)
        return True

    async def _announce_ready(self, meeting_id: str) -> None:
        """Tell anyone still watching. Never let it fail the job.

        The work is done and committed by this point, so a broken socket must
        not mark a succeeded job failed and re-run a paid LLM call. Whoever
        missed the message polls `GET /outputs` and gets the same answer.
        """
        if self._broadcaster is None:
            return
        try:
            await self._broadcaster.publish(meeting_id, OutputsReady().model_dump())
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "outputs_ready_broadcast_failed",
                meeting_id=meeting_id,
                error_type=type(exc).__name__,
            )

    async def _run_job(
        self, meeting_id: str, organization_id: str, payload: dict[str, object]
    ) -> None:
        async with session_scope() as db:
            segments = await SegmentRepository(db, organization_id).list_for_meeting(meeting_id)
            participants = await ParticipantRepository(db, organization_id).list_for_meeting(
                meeting_id
            )

        if not segments:
            raise RuntimeError("no final segments to summarize")

        display_names = {p.id: p.display_name for p in participants}
        user_prompt = build_user_prompt(segments, display_names)

        raw = await asyncio.wait_for(
            self._provider.complete_json(
                SYSTEM_PROMPT,
                user_prompt,
                MeetingIntelligence.model_json_schema(),
                LLM_DEADLINE_S,
            ),
            timeout=LLM_DEADLINE_S,
        )
        outputs = validate_outputs(raw, {s.id for s in segments})

        async with session_scope() as db:
            await OutputsRepository(db, organization_id).store(
                meeting_id=meeting_id,
                transcript_version=int(str(payload.get("transcript_version", 1))),
                processor_version=PROCESSOR_VERSION,
                llm_model=self._provider.model_name,
                outputs=outputs.model_dump(),
            )

    async def _record_failure(self, job_id: str, attempts: int, exc: Exception) -> None:
        reason = f"{exc.reason}: {exc}" if isinstance(exc, OutputValidationError) else str(exc)
        async with session_scope() as db:
            job = await db.get(Job, job_id)
            if job is None:
                return
            if attempts >= MAX_ATTEMPTS:
                job.status = "failed"
            else:
                job.status = "pending"
                backoff = BACKOFF_S[min(attempts - 1, len(BACKOFF_S) - 1)]
                job.next_run_at = datetime.now(UTC) + timedelta(seconds=backoff)
            job.last_error = reason[:500]
        log.warning("job_attempt_failed", job_id=job_id, attempts=attempts)
