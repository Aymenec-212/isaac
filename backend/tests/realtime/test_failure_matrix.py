"""The §14.1 failure matrix, driven through the real gateway.

These use the replay harness rather than a bespoke client, because §14.3 says
the harness is where disconnect-at-t and duplicate-frames-at-t belong: a
failure you can replay is a failure you can fix.

The bar each of these sets is the same one Slice 2 set for speed — an
interruption may cost a pause, but it may not change the transcript.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.replay import ReplayHarness, Scenario
from tools.replay.report import ReplayReport

from tests.conftest import host_token_for

pytestmark = pytest.mark.integration

SPEAKING_MS = 17_000


async def replay(live_server, settings, tenant, participants) -> ReplayReport:
    scenario = Scenario.from_dict(
        {"title": "Panne", "participants": participants},
        base_dir=Path("."),
        name="failure-matrix",
    )
    return await ReplayHarness(
        base_url=live_server.base_url,
        host_token=host_token_for(settings, tenant),
        scenario=scenario,
        speed=10.0,
    ).run()


def transcript_of(report: ReplayReport, name: str) -> list[str]:
    return [s.text for s in report.segments if s.display_name == name]


PHRASES = [
    "Bonjour, je pense qu'on peut commencer.",
    "Le budget du trimestre est validé.",
    "Il faut livrer la maquette avant vendredi.",
    "Sarah s'occupe de la relecture du contrat.",
    "On se revoit lundi prochain.",
]


async def test_a_disconnect_mid_meeting_costs_a_pause_not_a_segment(live_server, settings, tenants):
    """Failure matrix row 3, end to end.

    The socket is dropped in the middle of the fourth phrase and comes back a
    second later. Because the stream is held open, the transcript is the one an
    uninterrupted meeting would have produced.
    """
    report = await replay(
        live_server,
        settings,
        tenants["alpha"],
        [
            {
                "display_name": "Amina",
                "synthetic_ms": SPEAKING_MS,
                "disconnect_at_ms": 10_800,
                "reconnect_after_ms": 800,
            }
        ],
    )

    participant = report.participants[0]
    assert participant.disconnects == 1, "the harness never dropped the socket"
    assert participant.resumed is True, "the server did not resume the stream"
    assert transcript_of(report, "Amina") == PHRASES


async def test_replayed_frames_do_not_duplicate_the_transcript(live_server, settings, tenants):
    """Failure matrix row 4: duplicates are dropped, silently and correctly."""
    report = await replay(
        live_server,
        settings,
        tenants["alpha"],
        [
            {
                "display_name": "Amina",
                "synthetic_ms": SPEAKING_MS,
                "duplicate_at_ms": 7_000,
                "duplicate_frames": 24,
            }
        ],
    )

    assert report.participants[0].duplicates_sent == 24
    assert transcript_of(report, "Amina") == PHRASES


async def test_one_participant_dropping_does_not_disturb_the_other(live_server, settings, tenants):
    """Two streams, one interruption: the meeting is not a shared fate."""
    report = await replay(
        live_server,
        settings,
        tenants["alpha"],
        [
            {"display_name": "Amina", "synthetic_ms": SPEAKING_MS, "seed": 1},
            {
                "display_name": "Bruno",
                "start_ms": 1_600,
                "synthetic_ms": SPEAKING_MS,
                "seed": 5,
                "disconnect_at_ms": 6_400,
                "reconnect_after_ms": 600,
            },
        ],
    )

    assert transcript_of(report, "Amina") == PHRASES
    assert transcript_of(report, "Bruno") == PHRASES
    assert report.views_identical, "the two participants ended up seeing different transcripts"
