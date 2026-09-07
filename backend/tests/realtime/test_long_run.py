"""A long meeting, accelerated (tech spec 14.2, assumption A-9).

Deselected by default — it takes minutes. Run it deliberately:

    uv run pytest -m slow

What it is actually asking: does anything in the realtime path grow with the
length of a meeting? Every candidate is a per-stream structure the earlier
slices added — the segmenter's open segment, the audio queue, the pending
persistence buffer, the roster — and none of them should be larger after an
hour than after a minute.
"""

from __future__ import annotations

import gc
import tracemalloc
from pathlib import Path

import pytest
from tools.replay import ReplayHarness, Scenario

from tests.conftest import host_token_for

pytestmark = [pytest.mark.integration, pytest.mark.slow]

ONE_HOUR_MS = 60 * 60 * 1_000


async def test_an_hour_of_meeting_does_not_grow_the_runtime(live_server, settings, tenants):
    scenario = Scenario.from_dict(
        {
            "title": "Une heure",
            "participants": [
                {"display_name": "Amina", "synthetic_ms": ONE_HOUR_MS, "seed": 1},
                {
                    "display_name": "Bruno",
                    "start_ms": 1_600,
                    "synthetic_ms": ONE_HOUR_MS,
                    "seed": 5,
                },
            ],
        },
        base_dir=Path("."),
        name="one-hour",
    )

    gc.collect()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()

    report = await ReplayHarness(
        base_url=live_server.base_url,
        host_token=host_token_for(settings, tenants["alpha"]),
        scenario=scenario,
        speed=60.0,
        max_settle_s=120.0,
    ).run()

    gc.collect()
    after = tracemalloc.take_snapshot()
    growth = sum(stat.size_diff for stat in after.compare_to(before, "filename"))
    tracemalloc.stop()

    assert report.segments, "an hour of audio produced no transcript at all"
    assert report.stream_seconds >= 3_500, "the scenario did not actually run an hour"
    # The harness itself holds every message it received, so some growth is
    # expected and is the test's own doing. What would fail here is the
    # runtime leaking per-frame: an hour is 45 000 frames per stream.
    assert growth < 200 * 1024 * 1024, f"grew {growth / 1024 / 1024:.1f} MB over an hour"
