"""The timing script: who speaks, from when, out of which fixture.

`start_ms` — where a participant's stream is anchored on the meeting timeline —
is the one setting here with a non-obvious implementation, so it is worth
saying plainly what it does and why.

It is realised as a real wall-clock delay before that participant's socket
opens, and it is deliberately **not** divided by the speed factor. ADR-11
anchors a stream's `epoch_ms` to the server clock at the moment the stream
opens, and advances everything after it by frame counts. So a wall-constant
delay produces a meeting-time offset that is identical at 1x and at 10x, while
a delay scaled with the speed would shrink to a tenth and change the merged
transcript. The one wall-clock quantity in a replay is the one that has to stay
wall-clock.

Two approaches that look more natural do not work, and both are worth ruling
out in writing:

* prefixing the participant's audio with silence — `FakeRecognizer` advances
  its script on frames pushed, not on what the samples contain, so a silence
  prefix eats the start of the script instead of delaying it;
* starting the participant at a higher frame sequence — the gap is padded with
  silence on push, which advances the stream by exactly as much.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.replay.fixtures import load_pcm, synthetic_pcm


@dataclass(frozen=True)
class ParticipantScript:
    """One participant's stream."""

    display_name: str
    start_ms: int = 0
    pcm: str | None = None
    synthetic_ms: int | None = None
    seed: int = 1

    def __post_init__(self) -> None:
        if (self.pcm is None) == (self.synthetic_ms is None):
            raise ValueError(f"{self.display_name}: give exactly one of 'pcm' or 'synthetic_ms'")
        if self.start_ms < 0:
            raise ValueError(f"{self.display_name}: start_ms must not be negative")

    def audio(self, base_dir: Path) -> bytes:
        return (
            load_pcm(base_dir / self.pcm)
            if self.pcm is not None
            else synthetic_pcm(self.synthetic_ms or 0, seed=self.seed)
        )


@dataclass(frozen=True)
class Scenario:
    title: str
    speed: float
    participants: tuple[ParticipantScript, ...]
    base_dir: Path
    name: str

    @classmethod
    def load(cls, path: Path) -> Scenario:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(raw, base_dir=path.parent, name=path.name)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, base_dir: Path, name: str) -> Scenario:
        participants = tuple(ParticipantScript(**p) for p in raw["participants"])
        if not participants:
            raise ValueError("a scenario needs at least one participant")
        return cls(
            title=raw.get("title", "Replay"),
            speed=float(raw.get("speed", 1.0)),
            participants=participants,
            base_dir=base_dir,
            name=name,
        )
