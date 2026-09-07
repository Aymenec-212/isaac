"""The JSON report the harness writes.

Two latencies are recorded per segment, because one number cannot serve both
jobs the harness has:

* `first_word_latency_ms` — from the moment the first word of the segment
  *occurs on the meeting timeline* to the moment its interim text reached the
  client. This is the NFR in tech spec 1.3, and it is only meaningful at speed
  1.0: at 10x the harness deliberately runs ahead of the timeline, so the
  number goes negative and `totals.latency_meaningful` says so.
* `pipeline_latency_ms` — from the moment the harness put the covering frame
  on the wire to the moment the interim text came back. That is the server's
  own turnaround, and it is meaningful at any speed, which is what makes an
  accelerated replay useful for spotting a regression.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(int(p * len(ordered)), len(ordered) - 1)]


@dataclass(frozen=True)
class ParticipantRecord:
    participant_id: str
    display_name: str
    start_ms: int
    frames_sent: int
    speaking_transitions: int = 0


@dataclass(frozen=True)
class SegmentRecord:
    participant_id: str
    display_name: str
    sequence: int
    segment_id: str
    text: str
    start_ms: int
    end_ms: int
    duration_ms: int
    first_word_latency_ms: float | None
    pipeline_latency_ms: float | None


@dataclass
class ReplayReport:
    scenario: str
    speed: float
    meeting_id: str
    wall_seconds: float
    stream_seconds: float
    participants: list[ParticipantRecord] = field(default_factory=list)
    segments: list[SegmentRecord] = field(default_factory=list)
    deltas: int = 0
    sockets: int = 0
    broadcast_reached_every_socket: bool = True
    roster_complete: bool = True
    views_identical: bool = True
    finals_all_persisted: bool = True

    @property
    def totals(self) -> dict[str, Any]:
        first_word = [
            s.first_word_latency_ms for s in self.segments if s.first_word_latency_ms is not None
        ]
        pipeline = [
            s.pipeline_latency_ms for s in self.segments if s.pipeline_latency_ms is not None
        ]
        return {
            "segments": len(self.segments),
            "deltas": self.deltas,
            "speedup": (
                round(self.stream_seconds / self.wall_seconds, 2) if self.wall_seconds else None
            ),
            "latency_meaningful": self.speed == 1.0,
            "first_word_latency_ms_p50": _percentile(first_word, 0.50),
            "first_word_latency_ms_p95": _percentile(first_word, 0.95),
            "pipeline_latency_ms_p50": _percentile(pipeline, 0.50),
            "pipeline_latency_ms_p95": _percentile(pipeline, 0.95),
        }

    def transcript(self) -> list[dict[str, Any]]:
        """The merged transcript, in display order (tech spec 4)."""
        ordered = sorted(self.segments, key=lambda s: (s.start_ms, s.participant_id, s.sequence))
        return [
            {
                "display_name": s.display_name,
                "participant_id": s.participant_id,
                "sequence": s.sequence,
                "start_ms": s.start_ms,
                "text": s.text,
            }
            for s in ordered
        ]

    def signature(self) -> list[tuple[str, int, str, int]]:
        """What "the same transcript" means when comparing two speeds.

        Absolute `start_ms` cannot be in it. A participant's `epoch_ms` is
        anchored to the server clock at the moment its stream opens (ADR-11),
        so it carries a few milliseconds of connection jitter that differ
        between any two runs, at any speed. Everything the segmenter decides —
        who spoke, in what order, with what text, over how long — is derived
        from frame counts and is exactly reproducible.
        """
        return [
            (s.display_name, s.sequence, s.text, s.duration_ms)
            for s in sorted(self.segments, key=lambda s: (s.start_ms, s.participant_id, s.sequence))
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "speed": self.speed,
            "meeting_id": self.meeting_id,
            "wall_seconds": round(self.wall_seconds, 3),
            "stream_seconds": round(self.stream_seconds, 3),
            "broadcast": {
                "sockets": self.sockets,
                "reached_every_socket": self.broadcast_reached_every_socket,
                "roster_complete": self.roster_complete,
                "views_identical": self.views_identical,
                "finals_all_persisted": self.finals_all_persisted,
            },
            "participants": [asdict(p) for p in self.participants],
            "totals": self.totals,
            "transcript": self.transcript(),
            "segments": [asdict(s) for s in self.segments],
        }
