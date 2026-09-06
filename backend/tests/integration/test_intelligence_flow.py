"""Async meeting intelligence: job execution, retries, and the review payload."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from mosaique.intelligence.provider import FakeLLMProvider
from mosaique.jobs import MeetingIntelligenceProcessor
from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import Job, MeetingOutputs
from tests.conftest import host_token_for
from tests.integration.test_meeting_flow import (
    auth,
    create_and_join,
    stream_until_finals,
)

pytestmark = pytest.mark.integration


async def run_meeting_to_completion(ws_client, settings, tenant):
    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenant)
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        await ws.receive_json()
        await stream_until_finals(ws, frames=150, want=2)
    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))
    return token, meeting_id


async def test_outputs_return_202_until_the_job_has_run(ws_client, settings, tenants):
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    pending = await ws_client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(token))
    assert pending.status_code == 202
    assert pending.json()["status"] in {"pending", "running"}
    assert pending.json()["summary"] is None


async def test_processor_produces_evidence_linked_outputs(ws_client, settings, tenants):
    """The whole point of the slice's final step: a review page with citations."""
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    assert await MeetingIntelligenceProcessor(FakeLLMProvider()).run_once()

    ready = await ws_client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(token))
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "succeeded"
    assert body["summary"]
    assert body["decisions"] and body["action_items"]

    transcript = await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    known = {s["id"] for s in transcript.json()["segments"]}
    for item in body["decisions"] + body["action_items"]:
        assert item["evidence_segment_ids"]
        assert set(item["evidence_segment_ids"]) <= known, "evidence must be real"


async def test_a_failing_provider_leaves_transcript_and_meeting_untouched(
    ws_client, settings, tenants
):
    """Tech spec 14.1: a summary failure degrades, it does not destroy."""
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    processor = MeetingIntelligenceProcessor(FakeLLMProvider(fail_times=99))
    assert await processor.run_once()

    async with session_scope() as db:
        job = (await db.execute(select(Job).where(Job.meeting_id == meeting_id))).scalar_one()
        outputs = (
            (
                await db.execute(
                    select(MeetingOutputs).where(MeetingOutputs.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        )
    assert job.status == "pending"  # retried with backoff, not abandoned
    assert job.attempts == 1
    assert job.last_error
    assert outputs == [], "no outputs row may exist without success (X-12)"

    transcript = await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    assert transcript.status_code == 200
    assert transcript.json()["segments"], "transcript must survive a failed summary"

    meeting = await ws_client.http.get(f"/meetings/{meeting_id}", headers=auth(token))
    assert meeting.json()["state"] == "COMPLETED"


async def test_a_transient_failure_succeeds_on_retry(ws_client, settings, tenants):
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    provider = FakeLLMProvider(fail_times=1)
    processor = MeetingIntelligenceProcessor(provider)

    await processor.run_once()  # attempt 1 fails
    async with session_scope() as db:
        job = (await db.execute(select(Job).where(Job.meeting_id == meeting_id))).scalar_one()
        job.next_run_at = job.created_at  # skip the backoff wait
        job_id = job.id

    assert await processor.run_once()
    async with session_scope() as db:
        job = await db.get(Job, job_id)
        assert job is not None and job.status == "succeeded"

    ready = await ws_client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(token))
    assert ready.status_code == 200


async def test_running_the_processor_twice_does_not_duplicate_outputs(ws_client, settings, tenants):
    _, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    processor = MeetingIntelligenceProcessor(FakeLLMProvider())
    assert await processor.run_once()
    assert await processor.run_once() is False  # nothing left to claim

    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(MeetingOutputs).where(MeetingOutputs.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


async def test_outputs_are_not_readable_across_tenants(ws_client, settings, tenants):
    _, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    await MeetingIntelligenceProcessor(FakeLLMProvider()).run_once()
    beta = host_token_for(settings, tenants["beta"])
    denied = await ws_client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(beta))
    assert denied.status_code == 404


async def test_startup_recovery_completes_a_stranded_finalizing_meeting(
    ws_client, settings, tenants
):
    """Tech spec 11: a crash mid-finalization must not strand the meeting."""
    from mosaique.app.main import recover_finalizing_meetings
    from mosaique.persistence.models import Meeting

    token, meeting_id, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        await ws.receive_json()
        await stream_until_finals(ws, frames=120, want=1)
    await asyncio.sleep(0.2)

    # Simulate the crash: the meeting is left in FINALIZING with no live sessions.
    async with session_scope() as db:
        meeting = await db.get(Meeting, meeting_id)
        assert meeting is not None
        meeting.state = "FINALIZING"

    await recover_finalizing_meetings()

    async with session_scope() as db:
        meeting = await db.get(Meeting, meeting_id)
        assert meeting is not None
        assert meeting.state == "COMPLETED"
        assert meeting.transcript_version == 1

    transcript = await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    assert transcript.json()["segments"], "final segments survive the crash"
