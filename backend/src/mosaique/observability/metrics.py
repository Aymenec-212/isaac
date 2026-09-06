"""Metrics for Slice 1 (blueprint R-9).

Four only. The other twenty from tech spec 15 arrive in Slice 6, each with a
stated reason. Instrumenting everything now would be guessing at what matters.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Histogram:
    values: list[float] = field(default_factory=list)

    def observe(self, value: float) -> None:
        self.values.append(value)

    def percentile(self, p: float) -> float | None:
        if not self.values:
            return None
        ordered = sorted(self.values)
        index = min(int(p * len(ordered)), len(ordered) - 1)
        return ordered[index]


@dataclass
class Metrics:
    """In-process registry. A Prometheus exporter replaces this in Slice 6."""

    transcript_first_word_latency_ms: Histogram = field(default_factory=Histogram)
    audio_frames_received_total: int = 0
    audio_frames_rejected_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    meetings_completed_total: int = 0

    def frame_received(self) -> None:
        self.audio_frames_received_total += 1

    def frame_rejected(self, reason: str) -> None:
        self.audio_frames_rejected_total[reason] += 1

    def first_word_latency(self, ms: float) -> None:
        self.transcript_first_word_latency_ms.observe(ms)

    def meeting_completed(self) -> None:
        self.meetings_completed_total += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "audio_frames_received_total": self.audio_frames_received_total,
            "audio_frames_rejected_total": dict(self.audio_frames_rejected_total),
            "meetings_completed_total": self.meetings_completed_total,
            "transcript_first_word_latency_ms_p95": (
                self.transcript_first_word_latency_ms.percentile(0.95)
            ),
        }


METRICS = Metrics()
