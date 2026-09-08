"""Metrics for Slices 1-3 (blueprint R-9).

Four in Slice 1, plus one Slice 3 adds because the overload policy is
unobservable without it: a stream that skips frames looks identical to a quiet
one from the outside. The other twenty from tech spec 15 arrive in Slice 6,
each with a stated reason. Instrumenting everything now would be guessing at
what matters.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from mosaique.observability.latency import STAGE_NAMES, LatencyDecomposition, Stage


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
    asr_frames_skipped_total: int = 0
    # Slice 4: the `capture -> gateway_recv -> dequeue -> asr_first_event ->
    # broadcast` decomposition, accumulated across meetings. Per-meeting
    # numbers live on the runtime; these are what an operator would read.
    latency_stages: dict[str, Stage] = field(
        default_factory=lambda: {name: Stage(name) for name in STAGE_NAMES}
    )

    def merge_latency(self, decomposition: LatencyDecomposition) -> None:
        for name, stage in decomposition.stages.items():
            self.latency_stages.setdefault(name, Stage(name)).values.extend(stage.values)

    def frames_skipped(self, count: int) -> None:
        """Frames dropped from the ASR queue under overload (tech spec 8.4).

        Counted separately from `audio_frames_rejected`: a rejected frame was
        never valid, whereas a skipped one was good audio the recognizer could
        not keep up with. It is still on disk.
        """
        self.asr_frames_skipped_total += count

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
            "asr_frames_skipped_total": self.asr_frames_skipped_total,
            "transcript_first_word_latency_ms_p95": (
                self.transcript_first_word_latency_ms.percentile(0.95)
            ),
            "latency_stages_ms": {
                name: stage.summary() for name, stage in self.latency_stages.items()
            },
        }


METRICS = Metrics()
