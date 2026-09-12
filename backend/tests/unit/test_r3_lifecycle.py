"""R3 regressions: failure isolation, tail delivery and bounded lifecycle."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from mosaique.realtime.gateway import broadcaster as broadcast_module
from mosaique.realtime.gateway.broadcaster import SocketBroadcaster
from mosaique.realtime.gateway.ingress import BrowserWebSocketIngress
from mosaique.realtime.ingress import ParticipantLeft
from mosaique.realtime.sessions.registry import MeetingRegistry
from mosaique.speech.interfaces import ASRErrorEvent, ASRHealth, WordEvent
from tests.unit.test_stream_status import PCM

pytest_plugins = ["tests.unit.test_stream_status"]


class TailASR:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.count = 0
        self.closed = False

    async def events(self):
        while True:
            yield await self.queue.get()

    async def push_audio(self, chunk):
        pass

    async def flush(self):
        self.count += 1
        self.queue.put_nowait(WordEvent("dernier", 0, 80))

    async def close(self):
        self.closed = True

    def health(self):
        return ASRHealth(True, 0, None, self.count, 80)


async def test_tail_word_is_consumed_before_reader_and_asr_close(runtime_and_session):
    runtime, session, _ = runtime_and_session
    asr = TailASR()
    session.asr_session = asr
    session.accept(0, PCM, 0)
    await session.stop()
    await asyncio.wait_for(runtime._pump(session), 1)
    assert session.events_consumed == 1
    assert session.segmenter.has_open_segment
    assert asr.closed


@pytest.mark.parametrize("fault", ["open", "push", "reader", "fatal", "health"])
async def test_asr_failures_close_and_leave_recording_session_unavailable(
    runtime_and_session, fault
):
    runtime, session, broadcaster = runtime_and_session
    asr = TailASR()
    session.asr_session = asr
    if fault == "open":
        session.asr_session = None
        runtime._recognizer = type("Down", (), {"open_session": AsyncMock(side_effect=OSError)})()
    elif fault == "push":
        asr.push_audio = AsyncMock(side_effect=OSError)
    elif fault == "reader":

        async def broken():
            raise OSError()
            yield

        asr.events = broken
    elif fault == "fatal":
        asr.count = 1
        asr.queue.put_nowait(ASRErrorEvent("ASR_UNAVAILABLE", "down", True))
    else:
        asr.health = lambda: ASRHealth(False, 0, None)
    session.accept(0, PCM, 0)
    await asyncio.wait_for(runtime._pump(session), 1)
    assert session.failed_at is not None
    assert not session.closed  # recording/membership still owned by runtime
    await runtime._update_stream_status(session)
    assert broadcaster.published[-1]["status"] == "unavailable"
    if fault != "open":
        assert asr.closed


async def test_slow_peer_does_not_delay_delivery_to_healthy_peer(monkeypatch):
    monkeypatch.setattr(broadcast_module, "WRITE_TIMEOUT_S", 0.02)
    delivered = asyncio.Event()
    slow = type(
        "Slow",
        (),
        {"send_json": AsyncMock(side_effect=lambda _: asyncio.sleep(20)), "close": AsyncMock()},
    )()

    async def blocked(_):
        await asyncio.Event().wait()

    slow.send_json = blocked
    fast = type(
        "Fast",
        (),
        {"send_json": AsyncMock(side_effect=lambda _: delivered.set()), "close": AsyncMock()},
    )()
    broadcaster = SocketBroadcaster()
    await broadcaster.register("m", "slow", slow)
    await broadcaster.register("m", "fast", fast)
    task = asyncio.create_task(broadcaster.publish("m", {"type": "test"}))
    await asyncio.wait_for(delivered.wait(), 0.01)
    await asyncio.wait_for(task, 0.1)
    slow.close.assert_awaited_once()
    assert "slow" not in broadcaster._sockets["m"]


async def test_simultaneous_finalize_waits_for_same_durable_boundary():
    registry = MeetingRegistry(recognizer=None, audio_store=None, broadcaster=SocketBroadcaster())
    entered, release = asyncio.Event(), asyncio.Event()

    async def drain():
        entered.set()
        await release.wait()

    runtime = type("Runtime", (), {"drain": AsyncMock(side_effect=drain), "asr_version": "real"})()
    registry._runtimes["m"] = runtime
    first = asyncio.create_task(registry.finalize("m"))
    await entered.wait()
    second = asyncio.create_task(registry.finalize("m"))
    await asyncio.sleep(0)
    assert not second.done()
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    release.set()
    assert await second == "real"
    runtime.drain.assert_awaited_once()


async def test_ingress_seals_and_drains_every_accepted_event():
    ingress = BrowserWebSocketIngress(maxsize=1)
    event = ParticipantLeft(participant_id="p")
    assert ingress.submit(event)
    assert not ingress.submit(event)
    stop = asyncio.create_task(ingress.stop())
    await asyncio.sleep(0)
    assert not ingress.submit(event)
    assert [item async for item in ingress.events()] == [event]
    await stop


async def test_failed_drain_is_shared_and_never_returns_success():
    registry = MeetingRegistry(recognizer=None, audio_store=None, broadcaster=SocketBroadcaster())
    runtime = type(
        "Runtime", (), {"drain": AsyncMock(side_effect=OSError), "asr_version": "real"}
    )()
    registry._runtimes["m"] = runtime
    results = await asyncio.gather(
        registry.finalize("m"), registry.finalize("m"), return_exceptions=True
    )
    assert all(isinstance(result, OSError) for result in results)
    runtime.drain.assert_awaited_once()


async def test_stop_never_waits_for_space_in_failed_asr_queue(runtime_and_session):
    _, session, _ = runtime_and_session
    for seq in range(62):
        session.accept(seq, PCM, 0)
    await asyncio.wait_for(session.stop(), 0.02)
    for _ in range(62):
        assert await session.next_frame() is not None
    assert await session.next_frame() is None


async def test_flush_exception_is_a_visible_gap_not_success(runtime_and_session):
    runtime, session, _ = runtime_and_session
    asr = TailASR()
    asr.flush = AsyncMock(side_effect=TimeoutError)
    session.asr_session = asr
    session.accept(0, PCM, 0)
    await session.stop()
    await runtime._pump(session)
    assert session.failed_at is not None and session.gap_from is not None
    assert asr.closed


async def test_one_deadline_bounds_all_streams(runtime_and_session):
    runtime, session, _ = runtime_and_session
    runtime._ingress = BrowserWebSocketIngress()
    runtime._sessions = {"p1": session, "p2": session}

    async def never(_):
        await asyncio.Event().wait()

    runtime._finish_stream = AsyncMock(side_effect=never)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(runtime.drain(deadline_s=0.02), 0.1)
    assert runtime._draining


async def test_ingress_rejection_closes_socket_with_explicit_error():
    from mosaique.realtime.gateway.endpoint import _submit

    ingress = BrowserWebSocketIngress(maxsize=1)
    event = ParticipantLeft(participant_id="p")
    assert ingress.submit(event)
    socket = type("Socket", (), {"send_json": AsyncMock(), "close": AsyncMock()})()
    assert not await _submit(ingress, event, socket)
    assert socket.send_json.call_args.args[0]["code"] == "INGRESS_UNAVAILABLE"
    socket.close.assert_awaited_once_with(code=1013)
