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
    offer = RTCOffer(type="rtc.offer", target_participant_id="peer", sdp="v=0")
    answer = RTCAnswer(type="rtc.answer", target_participant_id="peer", sdp="v=0")
    candidate = RTCIceCandidate(
        type="rtc.ice",
        target_participant_id="peer",
        candidate="candidate:1 1 UDP 1 127.0.0.1 9 typ host",
        sdp_mid="0",
        sdp_m_line_index=0,
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
    registry.begin_flush("meeting-a", {"first", "second"})
    registry.acknowledge_flush("meeting-a", "first")
    assert not registry._flush_events["meeting-a"].is_set()
    registry.acknowledge_flush("meeting-a", "second")
    assert await asyncio.wait_for(registry.wait_for_flush("meeting-a", 0.1), 0.2)
