"""Where the time goes between a microphone and a browser (Slice 4).

`capture -> gateway_recv -> dequeue -> asr_first_event -> broadcast`. One
number for end-to-end latency says whether the NFR is met; these four say which
part to go and fix, and they exist because Slice 4 is the first slice where the
answer stops being "the fake's scripted 500 ms".

Two honesty notes, both of which are printed alongside the numbers rather than
buried here.

**`capture` comes from the client's clock.** `capture_ms` rides in the frame
header (spec 7.1) and ADR-11 forbids trusting it for ordering, which this does
not — but a `capture -> gateway_recv` delta still contains whatever skew exists
between two machines' clocks, and browsers do not agree with servers to the
millisecond. So the stage is recorded and reported *separately*, never folded
into the total, and `gateway_to_broadcast_ms` is the number to trust. In a
replay both ends are one process and the skew is genuinely zero, which is what
makes the harness the right place to read it.

**Stages are attributed to a frame, not to a segment.** A word's `start_ms`
names the audio it describes, so the frame covering that offset is the one whose
marks matter. Anything else measures the model delay twice.
"""

from __future__ import annotations

import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field

# Frames whose marks are kept per participant. 250 frames is 20 s of audio,
# comfortably longer than the model delay plus any queue backlog, and small
# enough that a four-hour meeting costs nothing.
TRACKED_FRAMES = 250


def now_ms() -> float:
    """Monotonic milliseconds. Never wall time: these are durations."""
    return time.monotonic() * 1000


@dataclass
class FrameMarks:
    sequence: int
    capture_ms: int | None
    gateway_recv_ms: float
    dequeue_ms: float | None = None


@dataclass
class Stage:
    """One hop, as a list of observed durations in milliseconds."""

    name: str
    values: list[float] = field(default_factory=list)

    def observe(self, ms: float) -> None:
        self.values.append(ms)

    def percentile(self, p: float) -> float | None:
        if not self.values:
            return None
        ordered = sorted(self.values)
        return ordered[min(int(p * len(ordered)), len(ordered) - 1)]

    def summary(self) -> dict[str, float | int | None]:
        return {
            "count": len(self.values),
            "p50": self.percentile(0.50),
            "p95": self.percentile(0.95),
            "max": max(self.values) if self.values else None,
        }


STAGE_NAMES = (
    "capture_to_gateway",
    "gateway_to_dequeue",
    "dequeue_to_first_event",
    "first_event_to_broadcast",
    "gateway_to_broadcast",
)


class LatencyDecomposition:
    """Per-frame marks in, per-stage distributions out.

    Not a metric registry: it holds the in-flight marks for recent frames and
    turns them into stage durations once the words they produced reach a client.
    """

    def __init__(self, tracked_frames: int = TRACKED_FRAMES) -> None:
        self._tracked = tracked_frames
        self._frames: dict[str, OrderedDict[int, FrameMarks]] = defaultdict(OrderedDict)
        # participant -> (when the first word arrived, when its frame landed).
        # Both are needed at broadcast time and they belong to one participant,
        # so they travel together rather than as two loose attributes.
        self._first_event: dict[str, tuple[float, float | None]] = {}
        self.stages: dict[str, Stage] = {name: Stage(name) for name in STAGE_NAMES}

    # ---- marks -----------------------------------------------------------

    def on_gateway_recv(self, participant_id: str, sequence: int, capture_ms: int | None) -> None:
        frames = self._frames[participant_id]
        frames[sequence] = FrameMarks(
            sequence=sequence, capture_ms=capture_ms, gateway_recv_ms=now_ms()
        )
        while len(frames) > self._tracked:
            frames.popitem(last=False)

    def on_dequeue(self, participant_id: str, sequence: int) -> None:
        marks = self._frames[participant_id].get(sequence)
        if marks is None:
            return
        marks.dequeue_ms = now_ms()
        self.stages["gateway_to_dequeue"].observe(marks.dequeue_ms - marks.gateway_recv_ms)

    def on_first_event(self, participant_id: str, stream_offset_ms: int, frame_ms: int) -> None:
        """A word arrived. Attribute it to the frame that carried its audio."""
        sequence = max(0, stream_offset_ms // frame_ms)
        marks = self._nearest(participant_id, sequence)
        at = now_ms()
        self._first_event[participant_id] = (
            at,
            None if marks is None else marks.gateway_recv_ms,
        )
        if marks is None or marks.dequeue_ms is None:
            return
        self.stages["dequeue_to_first_event"].observe(at - marks.dequeue_ms)
        if marks.capture_ms is not None:
            # Client clock minus server clock. Reported, never totalled.
            self.stages["capture_to_gateway"].observe(marks.gateway_recv_ms - marks.capture_ms)

    def on_broadcast(self, participant_id: str) -> None:
        pending = self._first_event.pop(participant_id, None)
        if pending is None:
            return
        first_event_ms, gateway_recv_ms = pending
        at = now_ms()
        self.stages["first_event_to_broadcast"].observe(at - first_event_ms)
        if gateway_recv_ms is not None:
            self.stages["gateway_to_broadcast"].observe(at - gateway_recv_ms)

    def _nearest(self, participant_id: str, sequence: int) -> FrameMarks | None:
        """The tracked frame at or just before `sequence`.

        A word's first frame may already have aged out of the ring on a badly
        lagging stream; falling back to the oldest tracked frame would invent a
        latency, so this returns None and the sample is simply not taken.
        """
        frames = self._frames.get(participant_id)
        if not frames:
            return None
        if sequence in frames:
            return frames[sequence]
        earlier = [seq for seq in frames if seq <= sequence]
        return frames[max(earlier)] if earlier else None

    # ---- output ----------------------------------------------------------

    def snapshot(self) -> dict[str, dict[str, float | int | None]]:
        return {name: stage.summary() for name, stage in self.stages.items()}

    def forget(self, participant_id: str) -> None:
        self._frames.pop(participant_id, None)
        self._first_event.pop(participant_id, None)
