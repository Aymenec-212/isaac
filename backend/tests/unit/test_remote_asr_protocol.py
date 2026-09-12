"""R2 regressions against a scripted pinned-protocol peer; no GPU claims."""

from __future__ import annotations

import asyncio

import pytest

from mosaique.speech.adapters.kyutai.moshi_server import MoshiServerBackend, MoshiSessionError
from mosaique.speech.adapters.kyutai.remote_recognizer import RemoteKyutaiRecognizer
from mosaique.speech.adapters.kyutai.transport import Message, TransportClosed
from mosaique.speech.interfaces import SILENCE_FRAME, ASRErrorEvent, ASRSessionConfig, WordEvent


class Peer:
    def __init__(self, *, ready=True, auto=False):
        self.inbound = asyncio.Queue()
        if ready:
            self.inbound.put_nowait({"type": "Ready"})
        self.auto = auto
        self.sent = []
        self.closed = False
        self.connects = 0
        self.marker = None

    async def connect(self):
        self.connects += 1

    async def close(self):
        self.closed = True

    async def receive(self):
        item = await self.inbound.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def send(self, message: Message):
        self.sent.append(message)
        if message["type"] == "Marker":
            self.marker = message["id"]
        elif self.auto and message["type"] == "Audio":
            self.inbound.put_nowait({"type": "Step", "step_idx": 5000, "prs": [0, 0, 0, 0]})
            if self.marker is not None:
                self.inbound.put_nowait({"type": "Marker", "id": self.marker})


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


async def started(peer=None, **kwargs):
    peer = peer or Peer()
    backend = MoshiServerBackend(peer, **kwargs)
    seen = []
    await backend.start(seen.append)
    return backend, peer, seen


async def test_start_waits_for_ready():
    peer = Peer(ready=False)
    backend = MoshiServerBackend(peer)
    task = asyncio.create_task(backend.start(lambda e: None))
    await settle()
    assert not task.done()
    with pytest.raises(MoshiSessionError):
        await backend.push(SILENCE_FRAME)
    assert peer.sent == []
    peer.inbound.put_nowait({"type": "Ready"})
    await task
    await backend.close()


async def test_ready_timeout_and_cancellation_release_socket():
    for cancel in [False, True]:
        peer = Peer(ready=False)
        backend = MoshiServerBackend(peer, ready_timeout_s=0.01)
        task = asyncio.create_task(backend.start(lambda e: None))
        if cancel:
            await settle()
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        assert peer.closed
        assert backend.closed


async def test_capacity_error_is_distinct_and_does_not_retry():
    peer = Peer(ready=False)
    peer.inbound.put_nowait({"type": "Error", "message": "no free channels"})
    with pytest.raises(MoshiSessionError) as caught:
        await MoshiServerBackend(peer).start(lambda e: None)
    assert caught.value.code == "ASR_CAPACITY_EXHAUSTED"
    assert peer.closed and peer.connects == 1


async def test_staggered_global_steps_do_not_shift_local_timeline():
    backend, peer, seen = await started()
    for _ in range(10):
        await backend.push(SILENCE_FRAME)
    for idx in range(10000, 10010):
        peer.inbound.put_nowait({"type": "Step", "step_idx": idx, "prs": [0, 0, 0.75, 0.99]})
    await settle()
    assert backend.processed_frames == 10
    assert seen[-1].at_ms == 320  # 10 * 80 - 6 * 80, not global batch time.
    assert seen[-1].probability == 0.75  # Two-second head, not final three-second head.
    await backend.close()


@pytest.mark.parametrize("prs", [[1, 1, 1], [0, 0, float("nan"), 1], [0, 0, True, 1], [0, 0, 2, 1]])
async def test_invalid_vad_is_not_a_turn_boundary(prs):
    backend, peer, seen = await started()
    peer.inbound.put_nowait({"type": "Step", "prs": prs})
    await settle()
    assert seen == []
    await backend.close()


async def test_tail_silence_and_matching_marker_are_required():
    backend, peer, seen = await started()
    await backend.push(SILENCE_FRAME)
    task = asyncio.create_task(backend.flush())
    await settle()
    assert [m["type"] for m in peer.sent] == ["Audio", "Marker", "Audio"]
    assert len(peer.sent[-1]["pcm"]) == 240000
    peer.inbound.put_nowait({"type": "Word", "text": "fin", "start_time": 0})
    peer.inbound.put_nowait({"type": "Marker", "id": 999})
    await settle()
    assert not task.done() and seen == []
    peer.inbound.put_nowait({"type": "EndWord", "stop_time": 0.08})
    peer.inbound.put_nowait({"type": "Marker", "id": 1})
    await task
    assert seen == [WordEvent(text="fin", start_ms=0, end_ms=80)]
    assert peer.closed
    with pytest.raises(MoshiSessionError):
        await backend.push(SILENCE_FRAME)


async def test_synthetic_tail_cannot_advance_past_input():
    backend, peer, seen = await started()
    await backend.push(SILENCE_FRAME)
    for _ in range(125):
        peer.inbound.put_nowait({"type": "Step", "prs": [0, 0, 0.9, 0]})
    await settle()
    assert backend.processed_frames * 80 - backend.delay_ms == 80
    assert seen[-1].at_ms == 80
    await backend.close()


async def test_flush_timeout_is_an_error_not_success():
    backend, peer, seen = await started(flush_timeout_s=0.01)
    with pytest.raises(MoshiSessionError) as caught:
        await backend.flush()
    assert caught.value.code == "ASR_FLUSH_TIMEOUT"
    assert peer.closed
    assert len([e for e in seen if isinstance(e, ASRErrorEvent)]) == 1


async def test_reader_failure_wakes_flush_and_releases_socket():
    backend, peer, seen = await started()
    task = asyncio.create_task(backend.flush())
    await settle()
    peer.inbound.put_nowait(TransportClosed("gone"))
    with pytest.raises(MoshiSessionError):
        await asyncio.wait_for(task, 0.5)
    assert peer.closed and peer.connects == 1
    assert len(seen) == 1 and seen[0].fatal


async def test_cancelled_flush_releases_socket():
    backend, peer, _ = await started()
    task = asyncio.create_task(backend.flush())
    await settle()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert peer.closed


async def test_readiness_requires_progress_and_caches_without_leaking_slot():
    peers = []

    def factory():
        peer = Peer(auto=True)
        peers.append(peer)
        return MoshiServerBackend(peer)

    recognizer = RemoteKyutaiRecognizer(factory)
    assert (await recognizer.readiness()).ready
    assert (await recognizer.readiness()).ready
    assert len(peers) == 1 and peers[0].closed


async def test_occupied_capacity_never_creates_a_probe_connection():
    peers = []

    def factory():
        peer = Peer(auto=True)
        peers.append(peer)
        return MoshiServerBackend(peer)

    recognizer = RemoteKyutaiRecognizer(factory)
    first = await recognizer.open_session(ASRSessionConfig())
    second = await recognizer.open_session(ASRSessionConfig())
    assert not (await recognizer.readiness()).ready
    with pytest.raises(MoshiSessionError):
        await recognizer.open_session(ASRSessionConfig())
    assert len(peers) == 2
    await first.close()
    third = await recognizer.open_session(ASRSessionConfig())
    assert third.health().transcribed_offset_ms == 0
    assert len(peers) == 3
    await second.close()
    await third.close()


async def test_inactive_probe_without_steps_is_not_ready():
    class MarkerOnlyPeer(Peer):
        async def send(self, message):
            if message["type"] == "Marker":
                self.inbound.put_nowait(message)

    peer = MarkerOnlyPeer()
    recognizer = RemoteKyutaiRecognizer(lambda: MoshiServerBackend(peer))
    assert not (await recognizer.readiness()).ready
    assert peer.closed


async def test_remote_session_health_turns_false_after_reader_failure():
    peer = Peer()
    recognizer = RemoteKyutaiRecognizer(lambda: MoshiServerBackend(peer))
    session = await recognizer.open_session(ASRSessionConfig())
    peer.inbound.put_nowait(TransportClosed("gone"))
    await settle()
    assert not session.health().healthy
    await session.close()


async def test_one_progressing_session_does_not_create_probe_or_reuse_cached_result():
    peer = Peer()
    recognizer = RemoteKyutaiRecognizer(lambda: MoshiServerBackend(peer))
    session = await recognizer.open_session(ASRSessionConfig())
    assert not (await recognizer.readiness()).ready
    peer.inbound.put_nowait({"type": "Step", "prs": [0, 0, 0, 0]})
    await settle()
    assert (await recognizer.readiness()).ready
    assert peer.connects == 1
    await session.close()


async def test_readiness_deadline_closes_unready_peer_and_caches_failure():
    peer = Peer(ready=False)
    recognizer = RemoteKyutaiRecognizer(lambda: MoshiServerBackend(peer), probe_timeout_s=0.01)
    assert not (await recognizer.readiness()).ready
    assert peer.closed
    assert not (await recognizer.readiness()).ready
    assert peer.connects == 1
