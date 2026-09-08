"""The Slice 4 latency decomposition (`capture -> ... -> broadcast`).

Pure arithmetic over injected marks, so the stages can be checked without a
meeting, a socket or a model.
"""

from __future__ import annotations

import pytest

from mosaique.observability.latency import TRACKED_FRAMES, LatencyDecomposition

FRAME_MS = 80


@pytest.fixture
def clock(monkeypatch):
    """A monotonic clock the test advances by hand."""
    ticks = {"now": 1_000.0}

    def now_ms() -> float:
        return ticks["now"]

    monkeypatch.setattr("mosaique.observability.latency.now_ms", now_ms)
    return ticks


def advance(clock, ms: float) -> None:
    clock["now"] += ms


def test_each_hop_is_measured_separately(clock):
    latency = LatencyDecomposition()

    latency.on_gateway_recv("p1", 10, capture_ms=None)
    advance(clock, 30)
    latency.on_dequeue("p1", 10)
    advance(clock, 500)
    latency.on_first_event("p1", 10 * FRAME_MS, FRAME_MS)
    advance(clock, 5)
    latency.on_broadcast("p1")

    stages = latency.snapshot()
    assert stages["gateway_to_dequeue"]["p50"] == 30
    assert stages["dequeue_to_first_event"]["p50"] == 500
    assert stages["first_event_to_broadcast"]["p50"] == 5
    assert stages["gateway_to_broadcast"]["p50"] == 535


def test_a_word_is_attributed_to_the_frame_that_carried_its_audio(clock):
    """Anything else measures the model delay twice."""
    latency = LatencyDecomposition()
    for sequence in range(5):
        latency.on_gateway_recv("p1", sequence, capture_ms=None)
        advance(clock, 10)
        latency.on_dequeue("p1", sequence)

    # A word describing audio at 160 ms belongs to frame 2, which was dequeued
    # at 1030 while the clock now reads 1050 — 20 ms, not the 50 ms since the
    # stream started. Attributing it to the newest frame instead would report
    # 0 ms and hide the model delay entirely.
    latency.on_first_event("p1", 160, FRAME_MS)

    assert latency.snapshot()["dequeue_to_first_event"]["p50"] == 20


def test_the_client_clock_hop_is_recorded_but_never_folded_into_the_total(clock):
    """`capture_ms` is the browser's clock; the delta carries skew, not just
    time. ADR-11 forbids trusting it, so it is reported on its own."""
    latency = LatencyDecomposition()
    latency.on_gateway_recv("p1", 0, capture_ms=900)
    latency.on_dequeue("p1", 0)
    latency.on_first_event("p1", 0, FRAME_MS)
    advance(clock, 7)
    latency.on_broadcast("p1")

    stages = latency.snapshot()
    assert stages["capture_to_gateway"]["p50"] == 100
    assert stages["gateway_to_broadcast"]["p50"] == 7  # the skew is not in here


def test_a_frame_that_aged_out_produces_no_sample_rather_than_a_wrong_one(clock):
    latency = LatencyDecomposition(tracked_frames=4)
    for sequence in range(10):
        latency.on_gateway_recv("p1", sequence, capture_ms=None)
        latency.on_dequeue("p1", sequence)

    latency.on_first_event("p1", 0, FRAME_MS)  # frame 0 is long gone
    latency.on_broadcast("p1")

    assert latency.snapshot()["dequeue_to_first_event"]["count"] == 0


def test_the_ring_does_not_grow_with_meeting_length(clock):
    latency = LatencyDecomposition()
    for sequence in range(TRACKED_FRAMES * 3):
        latency.on_gateway_recv("p1", sequence, capture_ms=None)

    assert len(latency._frames["p1"]) == TRACKED_FRAMES


def test_participants_do_not_share_in_flight_marks(clock):
    """Two pumps run concurrently; mixing their marks would invent latencies."""
    latency = LatencyDecomposition()
    latency.on_gateway_recv("p1", 0, capture_ms=None)
    latency.on_dequeue("p1", 0)
    advance(clock, 100)
    latency.on_gateway_recv("p2", 0, capture_ms=None)
    latency.on_dequeue("p2", 0)

    latency.on_first_event("p1", 0, FRAME_MS)
    latency.on_first_event("p2", 0, FRAME_MS)
    advance(clock, 3)
    latency.on_broadcast("p2")
    latency.on_broadcast("p1")

    assert latency.snapshot()["gateway_to_broadcast"]["count"] == 2
    assert latency.snapshot()["gateway_to_broadcast"]["max"] == 103


def test_forgetting_a_participant_releases_their_marks(clock):
    latency = LatencyDecomposition()
    latency.on_gateway_recv("p1", 0, capture_ms=None)
    latency.forget("p1")

    assert "p1" not in latency._frames
