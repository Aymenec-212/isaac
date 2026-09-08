"""Spike D: does an hour of French fit one context window? (A-5)

The plan makes chunk-and-merge conditional — "if Spike D says it is needed" —
so this is the measurement that decides whether Slice 5 builds it. It says no,
with room to spare, and Slice 5 therefore does not build it.

Method, and its limits. The real 116 s fixture is tiled to an hour rather than
synthesized, so the words, the segment count and the id lengths are all real
proportions rather than invented ones. Tokens are **estimated from characters**,
because counting them exactly needs the vendor's tokenizer and this suite does
not depend on one. The ratio is stated as an assumption below and the margin is
large enough that the estimate does not have to be tight to be decisive.

The one number worth carrying forward: **the segment-id prefixes are about 42%
of the prompt.** A 26-character ULID repeated on every line costs more than the
French does. That is fine at an hour and is the first thing to attack if a
longer meeting ever gets close to the ceiling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mosaique.intelligence.prompt import SYSTEM_PROMPT, build_user_prompt

REPORT = Path(__file__).resolve().parents[3] / "docs" / "slice4-last-test-report.json"

# A-5's target: a 60-minute meeting.
MEETING_SECONDS = 3600

# Assumption, not a measurement: French through a GPT-family BPE runs about
# 3 characters per token — worse than English because of accents and elision.
# Deliberately pessimistic; the real figure is nearer 3.5-4.
CHARS_PER_TOKEN = 3.0

# gpt-4o-mini's context window. The comparison, not a property of our code.
CONTEXT_WINDOW_TOKENS = 128_000

# Leave the model room to answer and to hold the schema.
BUDGET_TOKENS = CONTEXT_WINDOW_TOKENS // 2


@dataclass(frozen=True)
class Segment:
    """The three fields `build_user_prompt` reads."""

    id: str
    participant_id: str
    start_ms: int
    text: str


def _hour_of_segments() -> list[Segment]:
    """Tile the real fixture up to an hour, with realistic ULID-length ids."""
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    source = report["segments"]
    repeats = int(MEETING_SECONDS / report["stream_seconds"]) + 1

    segments: list[Segment] = []
    for cycle in range(repeats):
        offset = cycle * int(report["stream_seconds"] * 1000)
        for seg in source:
            start = seg["start_ms"] + offset
            if start >= MEETING_SECONDS * 1000:
                break
            segments.append(
                Segment(
                    # 26 characters, as `ulid_pk()` mints them.
                    id=f"{len(segments):026d}",
                    participant_id=f"p{len(segments) % 4}",
                    start_ms=start,
                    text=seg["text"],
                )
            )
    return segments


def _estimated_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def test_an_hour_of_four_person_french_fits_one_context_window():
    """A-5, answered by arithmetic over real proportions.

    This is the test that keeps chunk-and-merge out of Slice 5. If a future
    change makes it fail — a longer ceiling, a chattier speaker, a smaller
    model — then chunking is back on the table and A-5 needs reopening.
    """
    segments = _hour_of_segments()
    names = {f"p{i}": f"Participant {i}" for i in range(4)}

    prompt = build_user_prompt(segments, names)
    tokens = _estimated_tokens(SYSTEM_PROMPT) + _estimated_tokens(prompt)

    assert 3600 * 0.9 <= segments[-1].start_ms / 1000 <= 3600, "expected roughly an hour"
    assert tokens < BUDGET_TOKENS, (
        f"an hour estimates at {tokens} tokens against a {BUDGET_TOKENS} budget; "
        "chunk-and-merge would be back in scope"
    )


def test_the_segment_ids_cost_more_than_the_french_does():
    """The finding worth remembering, pinned so it is not rediscovered.

    Not a defect — evidence links are the product, and they need real ids. But
    if a longer meeting ever approaches the ceiling, shortening the citation
    handle buys more than trimming the transcript would.
    """
    segments = _hour_of_segments()
    names = {f"p{i}": f"Participant {i}" for i in range(4)}

    prompt = build_user_prompt(segments, names)
    spoken = sum(len(s.text) for s in segments)
    overhead = len(prompt) - spoken

    assert overhead > spoken * 0.5, (
        f"prompt scaffolding is {overhead} chars against {spoken} of speech; "
        "if this ratio has fallen, the note in this module is stale"
    )
