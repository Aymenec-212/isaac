"""Slice 2 exit gate: two streams, one merged transcript, at any speed.

These run the harness the way a person does — against an app-server in its own
process, over a real WebSocket — so what passes here is what a browser gets.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.replay import ReplayHarness, Scenario
from tools.replay.report import ReplayReport

from tests.conftest import host_token_for

pytestmark = pytest.mark.integration

# 17 s of audio per participant. The scripted French dialogue ends at 15.7 s of
# stream and the fake recognizer runs 500 ms behind it, so anything past ~16.3 s
# guarantees the whole script is emitted and consumed before the meeting ends.
SPEAKING_MS = 17_000
BRUNO_START_MS = 1_600

# `DEFAULT_SCRIPT`, one entry per phrase. Segment boundaries are decided in
# stream time from frame counts, so every participant gets exactly these five
# segments at every speed. A split phrase means something has started judging
# silence against audio *pushed* rather than audio transcribed.
PHRASES = [
    "Bonjour, je pense qu'on peut commencer.",
    "Le budget du trimestre est validé.",
    "Il faut livrer la maquette avant vendredi.",
    "Sarah s'occupe de la relecture du contrat.",
    "On se revoit lundi prochain.",
]

SCENARIO = {
    "title": "Deux participants",
    "participants": [
        {"display_name": "Amina", "start_ms": 0, "synthetic_ms": SPEAKING_MS, "seed": 1},
        {
            "display_name": "Bruno",
            "start_ms": BRUNO_START_MS,
            "synthetic_ms": SPEAKING_MS,
            "seed": 5,
        },
    ],
}


async def replay_at(
    live_server, settings, tenant, speed: float, scenario_dict: dict | None = None
) -> ReplayReport:
    scenario = Scenario.from_dict(
        scenario_dict or SCENARIO, base_dir=Path("."), name="two-participants"
    )
    harness = ReplayHarness(
        base_url=live_server.base_url,
        host_token=host_token_for(settings, tenant),
        scenario=scenario,
        speed=speed,
    )
    return await harness.run()


async def test_the_harness_merges_two_attributed_streams(live_server, settings, tenants):
    """The Slice 2 gate: two participants, one correctly attributed transcript."""
    report = await replay_at(live_server, settings, tenants["alpha"], speed=10.0)

    assert report.sockets == 2
    assert report.broadcast_reached_every_socket, "a final never reached a connected socket"
    assert report.views_identical, "the two participants ended up seeing different transcripts"
    assert report.finals_all_persisted, "a broadcast final was never written to the database"

    by_name: dict[str, list[str]] = {}
    for segment in report.segments:
        by_name.setdefault(segment.display_name, []).append(segment.text)
    assert set(by_name) == {"Amina", "Bruno"}, f"only heard from {sorted(by_name)}"

    # Each participant is transcribed independently, completely, and without a
    # phrase being split across two segments.
    for name, texts in by_name.items():
        assert texts == PHRASES, f"{name} was segmented as {texts}"

    # One participant's segments never carry another's id.
    ids = {s.display_name: {s.participant_id} for s in report.segments}
    assert len(ids["Amina"] | ids["Bruno"]) == 2

    # Display order is by start time across participants (tech spec 4).
    merged = report.transcript()
    assert [m["start_ms"] for m in merged] == sorted(m["start_ms"] for m in merged)
    speakers = [m["display_name"] for m in merged]
    assert "Amina" in speakers and "Bruno" in speakers
    assert speakers != sorted(speakers), "the two streams never interleaved"

    # Bruno's later join anchors his whole stream behind Amina's (ADR-11). The
    # tolerance is the WebSocket handshake: `epoch_ms` is fixed when the server
    # opens the stream, a little after the harness starts connecting.
    first = {
        name: min(s.start_ms for s in report.segments if s.display_name == name)
        for name in ("Amina", "Bruno")
    }
    assert first["Bruno"] - first["Amina"] == pytest.approx(BRUNO_START_MS, abs=400)


async def test_ten_times_speed_produces_the_same_transcript_as_real_time(
    live_server, settings, tenants
):
    """ADR-11 in one assertion.

    Segmentation is judged in stream time, derived from frame counts, so the
    speed factor may not change a single word or boundary. When this fails,
    something has started comparing stream time against a wall clock — the bug
    Slice 1 already had once.
    """
    real_time = await replay_at(live_server, settings, tenants["alpha"], speed=1.0)
    accelerated = await replay_at(live_server, settings, tenants["alpha"], speed=10.0)

    assert real_time.signature() == accelerated.signature()
    assert real_time.segments, "the real-time replay produced no segments at all"
    assert accelerated.wall_seconds < real_time.wall_seconds / 4


async def test_the_runtime_announces_the_roster_and_who_is_speaking(live_server, settings, tenants):
    """The participant panel's data, and where the runtime is allowed to get it.

    The roster is built from ingress events only; the runtime never asks the
    transport how many sockets are open (blueprint D-04). Speaking is derived
    from the segmenter, so it means "recognized speech", not "microphone noise",
    and costs nothing extra on the wire.
    """
    report = await replay_at(live_server, settings, tenants["alpha"], speed=10.0)

    assert report.roster_complete, "a socket was never told about the other participant"
    for participant in report.participants:
        assert participant.speaking_transitions >= 2, (
            f"{participant.display_name} never showed as speaking and then stopped"
        )


async def test_the_report_records_per_segment_first_word_latency(live_server, settings, tenants):
    """A deliberately short scenario: this checks the report, not the transcript."""
    short = {
        "title": "Latence",
        "participants": [
            {"display_name": "Amina", "start_ms": 0, "synthetic_ms": 5_000, "seed": 1},
            {"display_name": "Bruno", "start_ms": 400, "synthetic_ms": 5_000, "seed": 5},
        ],
    }
    report = await replay_at(
        live_server, settings, tenants["alpha"], speed=1.0, scenario_dict=short
    )

    assert report.totals["latency_meaningful"] is True
    assert all(s.first_word_latency_ms is not None for s in report.segments)
    assert all(s.pipeline_latency_ms is not None for s in report.segments)
    # Text cannot come back before the audio carrying it went out.
    assert all(s.pipeline_latency_ms >= 0 for s in report.segments)  # type: ignore[operator]
    assert report.totals["first_word_latency_ms_p95"] is not None

    payload = report.to_dict()
    assert payload["participants"][0]["speaking_transitions"] > 0
    assert payload["broadcast"] == {
        "sockets": 2,
        "reached_every_socket": True,
        "roster_complete": True,
        "views_identical": True,
        "finals_all_persisted": True,
    }
    assert payload["transcript"] and payload["segments"]
