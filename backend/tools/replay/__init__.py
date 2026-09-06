"""Replay harness v1 (tech spec 14.3, Slice 2).

The primary debugging tool for the realtime path. It drives the *real* gateway
over a real WebSocket — the same route a browser takes — with N recorded or
synthetic participant streams, at a chosen speed factor, and writes a JSON
report.

Two properties make it worth having:

* **It is deterministic.** Meeting time is derived from frame counts (ADR-11),
  and the fake recognizer advances on frames rather than on a clock, so a
  replay at 10x produces the same transcript as one at 1x. `--speed` is
  therefore a free win: a 30-minute scenario is a 3-minute test.
* **It is out-of-process.** Nothing here reaches into the runtime. If the
  harness can reproduce a failure, so can a browser.

Slice 3 uses it to inject disconnects; Slice 4 tunes the segmentation
thresholds with it against real French audio.
"""

from tools.replay.harness import ReplayHarness
from tools.replay.report import ReplayReport, SegmentRecord
from tools.replay.scenario import ParticipantScript, Scenario

__all__ = [
    "ParticipantScript",
    "ReplayHarness",
    "ReplayReport",
    "Scenario",
    "SegmentRecord",
]
