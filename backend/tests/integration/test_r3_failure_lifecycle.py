"""R3 through the real gateway, PostgreSQL and PCM files; ASR is scripted."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from mosaique.intelligence.provider import FakeLLMProvider
from mosaique.jobs import MeetingIntelligenceProcessor
from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import AudioSession, Job, Meeting, TranscriptSegment
from mosaique.realtime.sessions import meeting as module
from mosaique.speech.audio import LocalAudioStore
from tests.integration.test_meeting_flow import PCM, auth, create_and_join, stream_until_finals
from tests.realtime.test_idle_and_pause import join_two
from tests.realtime.test_reconnect import hello, stream

pytestmark = pytest.mark.integration


async def test_open_failure_preserves_both_recordings_and_recovers_fresh_epoch(
    ws_client, settings, tenants, tmp_path, monkeypatch
):
    token, mid, (a, b) = await join_two(ws_client.http, settings, tenants["alpha"])
    pid = a["participant"]["id"]
    recognizer = ws_client.registry.recognizer
    original = recognizer.open_session
    unavailable = True

    async def opening(cfg):
        if cfg.correlation["participant_id"] == pid and unavailable:
            await asyncio.sleep(0.03)
            raise OSError("injected ASR outage")
        return await original(cfg)

    monkeypatch.setattr(recognizer, "open_session", opening)
    monkeypatch.setattr(module, "ASR_RETRY_S", 0.05)
    ws_client.registry._audio_store = LocalAudioStore(tmp_path)
    async with (
        ws_client.websocket_connect(f"/ws/meetings/{mid}") as wa,
        ws_client.websocket_connect(f"/ws/meetings/{mid}") as wb,
    ):
        await hello(wa, a["session_token"])
        await hello(wb, b["session_token"])
        # Keep retry off until the explicit recovery phase.
        monkeypatch.setattr(module, "ASR_RETRY_S", 10)
        await asyncio.gather(stream(wa, start=0, count=30), stream(wb, start=0, count=50))
        runtime = ws_client.registry.get(mid)
        first = runtime._sessions[pid]
        assert first.failed_at is not None
        assert runtime._sessions[b["participant"]["id"]].frames_pushed == 50
        assert runtime._file_frames[pid] == 30
        assert runtime._stream_status[pid] == "unavailable"
        assert pid in runtime._roster
        unavailable = False
        monkeypatch.setattr(module, "ASR_RETRY_S", 0)
        await stream(wa, start=30, count=30)
        second = runtime._sessions[pid]
        assert second.audio_session_id != first.audio_session_id
        assert second.sequence_base == 30
        assert second.frames_pushed == 30
        assert second.epoch_ms > first.epoch_ms
        assert runtime.resume_info(pid).last_sequence == 59
        result = await ws_client.http.post(f"/meetings/{mid}/end", headers=auth(token))
        assert result.status_code == 200, result.text
    async with session_scope() as db:
        rows = (
            (await db.execute(select(AudioSession).where(AudioSession.meeting_id == mid)))
            .scalars()
            .all()
        )
        gaps = (
            (
                await db.execute(
                    select(TranscriptSegment).where(
                        TranscriptSegment.meeting_id == mid, TranscriptSegment.status == "gap"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 3 and all(r.ended_at is not None for r in rows)
    own = [r for r in rows if r.participant_id == pid]
    assert len(own) == 2
    for row in own:
        assert (
            b"".join(
                ws_client.registry.audio_store.read_range(row.audio_object_key, 0, len(PCM) * 30)
            )
            == PCM * 30
        )
    assert len(gaps) == 1
    assert gaps[0].audio_session_id == first.audio_session_id
    assert gaps[0].end_ms - gaps[0].start_ms == 30 * 80


async def test_concurrent_http_end_does_not_complete_or_enqueue_before_drain(
    ws_client, settings, tenants, monkeypatch
):
    token, mid, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    entered, release = asyncio.Event(), asyncio.Event()
    async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as ws:
        await hello(ws, joined["session_token"])
        await stream(ws, start=0, count=20)
        runtime = ws_client.registry.get(mid)
        original = runtime.drain

        async def slow():
            entered.set()
            await release.wait()
            await original()

        monkeypatch.setattr(runtime, "drain", slow)
        first = asyncio.create_task(
            ws_client.http.post(f"/meetings/{mid}/end", headers=auth(token))
        )
        await entered.wait()
        second = asyncio.create_task(
            ws_client.http.post(f"/meetings/{mid}/end", headers=auth(token))
        )
        await asyncio.sleep(0.03)
        assert not first.done() and not second.done()
        async with session_scope() as db:
            assert (await db.get(Meeting, mid)).state == "FINALIZING"
            assert not (await db.execute(select(Job).where(Job.meeting_id == mid))).scalars().all()
        release.set()
        results = await asyncio.gather(first, second)
        assert all(r.status_code == 200 for r in results)
    async with session_scope() as db:
        jobs = (await db.execute(select(Job).where(Job.meeting_id == mid))).scalars().all()
        assert len(jobs) == 1
        assert (await db.get(Meeting, mid)).state == "COMPLETED"


async def test_persistence_failure_at_end_marks_failed_and_enqueues_nothing(
    ws_client, settings, tenants, monkeypatch
):
    token, mid, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as ws:
        await hello(ws, joined["session_token"])
        await stream(ws, start=0, count=20)
        runtime = ws_client.registry.get(mid)
        monkeypatch.setattr(runtime, "_retry_pending", AsyncMock(side_effect=OSError))
        result = await ws_client.http.post(f"/meetings/{mid}/end", headers=auth(token))
        assert result.status_code >= 400
    async with session_scope() as db:
        assert (await db.get(Meeting, mid)).state == "FAILED"
        assert not (await db.execute(select(Job).where(Job.meeting_id == mid))).scalars().all()


@pytest.mark.parametrize("attempts, expected", [(1, "pending"), (3, "failed")])
async def test_startup_recovers_running_jobs_with_bounded_attempts(
    ws_client, settings, tenants, attempts, expected
):
    token, mid, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as ws:
        await hello(ws, joined["session_token"])
        await stream_until_finals(ws, frames=100, want=1)
        await ws_client.http.post(f"/meetings/{mid}/end", headers=auth(token))
    async with session_scope() as db:
        job = (await db.execute(select(Job).where(Job.meeting_id == mid))).scalar_one()
        job.status, job.attempts = "running", attempts
        jid = job.id
    processor = MeetingIntelligenceProcessor(FakeLLMProvider())
    assert await processor.recover_running() == 1
    assert await processor.recover_running() == 0
    async with session_scope() as db:
        assert (await db.get(Job, jid)).status == expected


async def test_recovery_of_committed_outputs_does_not_repeat_provider_call(
    ws_client, settings, tenants
):
    token, mid, joined = await create_and_join(ws_client.http, settings, tenants["alpha"])
    async with ws_client.websocket_connect(f"/ws/meetings/{mid}") as ws:
        await hello(ws, joined["session_token"])
        await stream_until_finals(ws, frames=100, want=1)
        await ws_client.http.post(f"/meetings/{mid}/end", headers=auth(token))
    processor = MeetingIntelligenceProcessor(FakeLLMProvider())
    assert await processor.run_once()
    async with session_scope() as db:
        job = (await db.execute(select(Job).where(Job.meeting_id == mid))).scalar_one()
        job.status = "running"  # crash after outputs commit, before status commit
        jid = job.id
    assert await processor.recover_running() == 1
    assert not await processor.run_once()
    async with session_scope() as db:
        assert (await db.get(Job, jid)).status == "succeeded"


async def test_blocked_asr_open_does_not_block_other_participant_or_recording(
    ws_client, settings, tenants, tmp_path, monkeypatch
):
    token, mid, (a, b) = await join_two(ws_client.http, settings, tenants["alpha"])
    pid = a["participant"]["id"]
    entered, release = asyncio.Event(), asyncio.Event()
    recognizer = ws_client.registry.recognizer
    original = recognizer.open_session

    async def opening(cfg):
        if cfg.correlation["participant_id"] == pid:
            entered.set()
            await release.wait()
        return await original(cfg)

    monkeypatch.setattr(recognizer, "open_session", opening)
    ws_client.registry._audio_store = LocalAudioStore(tmp_path)
    async with (
        ws_client.websocket_connect(f"/ws/meetings/{mid}") as wa,
        ws_client.websocket_connect(f"/ws/meetings/{mid}") as wb,
    ):
        await hello(wa, a["session_token"])
        await entered.wait()
        await hello(wb, b["session_token"])
        await asyncio.gather(stream(wa, start=0, count=10), stream(wb, start=0, count=50))
        runtime = ws_client.registry.get(mid)
        assert runtime._sessions[pid].asr_session is None
        assert runtime._file_frames[pid] == 10
        assert runtime._sessions[b["participant"]["id"]].frames_pushed == 50
        release.set()
        result = await ws_client.http.post(f"/meetings/{mid}/end", headers=auth(token))
        assert result.status_code == 200


async def test_failed_audio_storage_reports_failure_without_stopping_peer(
    ws_client, settings, tenants, monkeypatch
):
    _, mid, (a, b) = await join_two(ws_client.http, settings, tenants["alpha"])
    pid = a["participant"]["id"]
    async with (
        ws_client.websocket_connect(f"/ws/meetings/{mid}") as wa,
        ws_client.websocket_connect(f"/ws/meetings/{mid}") as wb,
    ):
        await hello(wa, a["session_token"])
        await hello(wb, b["session_token"])
        await stream(wa, start=0, count=1)
        runtime = ws_client.registry.get(mid)
        original = runtime._write_arrival

        def write(session, seq, pcm):
            if session.participant_id == pid:
                raise OSError("disk full")
            original(session, seq, pcm)

        monkeypatch.setattr(runtime, "_write_arrival", write)
        await asyncio.gather(stream(wa, start=1, count=5), stream(wb, start=0, count=20))
        assert runtime._sessions[pid].recording_failed
        assert runtime._stream_status[pid] == "unavailable"
        assert runtime._sessions[b["participant"]["id"]].frames_pushed == 20
        assert any(m.get("code") == "AUDIO_RECORDING_FAILED" for m in wa.drain())
