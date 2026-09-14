"""R5's transport-side WebRTC contracts and peer routing."""

import asyncio

import pytest
from pydantic import ValidationError

from mosaique.realtime.gateway.broadcaster import SocketBroadcaster
from mosaique.realtime.protocol.messages import RTCAnswer, RTCIceCandidate, RTCOffer


class FakeSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_json(self, data: dict[str, object]) -> None:
        self.messages.append(data)

    async def close(self, code: int = 1000) -> None:
        del code


def test_rtc_messages_are_versioned_and_bound_to_a_target() -> None:
    generation = dict(connection_id="a", target_connection_id="b", negotiation_id="n")
    offer = RTCOffer(type="rtc.offer", target_participant_id="peer", sdp="v=0", **generation)
    answer = RTCAnswer(type="rtc.answer", target_participant_id="peer", sdp="v=0", **generation)
    candidate = RTCIceCandidate(
        type="rtc.ice",
        target_participant_id="peer",
        candidate="candidate:1 1 UDP 1 127.0.0.1 9 typ host",
        sdp_mid="0",
        sdp_m_line_index=0,
        **generation,
    )
    assert offer.v == answer.v == candidate.v == 1
    with pytest.raises(ValidationError):
        RTCOffer(type="rtc.offer", target_participant_id="", sdp="v=0")


@pytest.mark.asyncio
async def test_signaling_delivery_is_scoped_to_the_meeting_and_target() -> None:
    broadcaster = SocketBroadcaster()
    first, second, other = FakeSocket(), FakeSocket(), FakeSocket()
    await broadcaster.register("meeting-a", "first", first)
    await broadcaster.register("meeting-a", "second", second)
    await broadcaster.register("meeting-b", "second", other)

    delivered = await broadcaster.send_to_meeting("meeting-a", "second", {"type": "rtc.offer"})

    assert delivered
    assert second.messages == [{"type": "rtc.offer"}]
    assert other.messages == []
    assert first.messages == []
    assert not await broadcaster.send_to_meeting("meeting-a", "missing", {"type": "rtc.offer"})


@pytest.mark.asyncio
async def test_flush_waiter_completes_only_after_every_connected_peer_acknowledges() -> None:
    # Keep this contract test independent of PostgreSQL and the ASR runtime.
    from mosaique.realtime.sessions.registry import MeetingRegistry

    registry = MeetingRegistry.__new__(MeetingRegistry)
    registry._flush_waiters = {}
    registry._flush_events = {}
    registry._flush_requests = {}
    registry.begin_flush("meeting-a", {"first": "a", "second": "b"}, "request")
    assert not registry.acknowledge_flush("meeting-a", "first", "old", "request")
    assert not registry.acknowledge_flush("meeting-a", "first", "a", "old-request")
    registry.acknowledge_flush("meeting-a", "first", "a", "request")
    assert not registry._flush_events["meeting-a"].is_set()
    registry.acknowledge_flush("meeting-a", "second", "b", "request")
    assert await asyncio.wait_for(registry.wait_for_flush("meeting-a", 0.1), 0.2)


async def test_generation_routing_rejects_replaced_sender_and_target():
    broadcaster = SocketBroadcaster()
    a, b, replacement = FakeSocket(), FakeSocket(), FakeSocket()
    await broadcaster.register("m", "a", a)
    await broadcaster.register("m", "b", b)
    await broadcaster.voice_ready("m", "a", a, "a1")
    await broadcaster.voice_ready("m", "b", b, "b1")
    message = {
        "v": 1,
        "type": "rtc.offer",
        "connection_id": "a1",
        "target_connection_id": "b1",
        "negotiation_id": "n",
    }
    assert await broadcaster.forward_signal("m", "a", a, "b", message)
    await broadcaster.register("m", "b", replacement)
    await broadcaster.voice_ready("m", "b", replacement, "b2")
    assert not await broadcaster.forward_signal("m", "a", a, "b", message)
    assert not await broadcaster.unregister("m", "b", b)
    assert broadcaster.voice_connections("m") == {"a": "a1", "b": "b2"}
    await broadcaster.register("m", "a", replacement)
    assert not await broadcaster.forward_signal("m", "a", a, "b", message)


async def test_concurrent_finalize_shares_handshake_and_remaining_deadline():
    from unittest.mock import AsyncMock

    from mosaique.realtime.sessions.registry import MeetingRegistry

    broadcaster = SocketBroadcaster()
    socket = FakeSocket()
    await broadcaster.register("m", "p", socket)
    await broadcaster.voice_ready("m", "p", socket, "connection")
    registry = MeetingRegistry(recognizer=None, audio_store=None, broadcaster=broadcaster)
    runtime = type("Runtime", (), {"drain": AsyncMock(), "asr_version": "fake"})()
    registry._runtimes["m"] = runtime
    first = asyncio.create_task(registry.finalize("m"))
    second = asyncio.create_task(registry.finalize("m"))
    async with asyncio.timeout(1):
        while not any(m["type"] == "meeting.end_requested" for m in socket.messages):
            await asyncio.sleep(0)
    requests = [m for m in socket.messages if m["type"] == "meeting.end_requested"]
    assert len(requests) == 1
    assert registry.acknowledge_flush("m", "p", "connection", requests[0]["request_id"])
    assert await asyncio.gather(first, second) == ["fake", "fake"]
    runtime.drain.assert_awaited_once()
    assert 0 < runtime.drain.call_args.kwargs["deadline_s"] < 20


@pytest.mark.parametrize(
    "changes",
    [
        {"webrtc_turn_urls": ["turn:example.org"]},
        {"webrtc_stun_urls": ["https://example.org"]},
        {"webrtc_ice_transport_policy": "relay"},
        {"webrtc_turn_urls": ["turn:user:password@example.org"], "webrtc_turn_shared_secret": "s"},
    ],
)
def test_invalid_ice_configuration_fails_at_startup(changes):
    from mosaique.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://a:b@localhost/test", token_secret="s" * 32, **changes
        )
