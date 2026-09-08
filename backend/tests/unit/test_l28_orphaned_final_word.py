"""L-28, pinned so it cannot be forgotten (deferred 2026-09-08, not fixed).

**This file asserts behaviour that is wrong.** It is a characterization test:
it describes what the system currently does with real audio, so that the defect
stays visible in the suite while it is deferred, and so that fixing it is a
deliberate act with a failing test to prove it rather than something nobody
notices happened.

The defect: on the first real French fixture, the segmenter closed 8 of 30
segments immediately before the last word of a sentence, leaving that word
alone in a 160-400 ms segment (`tous.`, `technologie.`, `cardinale.`, …).

What is proven, and what this file therefore asserts:

* the pattern is present, and how often;
* it cannot be caused by silence in the recording — the acoustic gap before
  each orphan is far below the 1 200 ms threshold that closes a segment.

What is **not** proven and is deliberately not asserted anywhere here: *why*
the offset ran ahead of the words. The standing hypothesis is emission lag —
the runtime withholding a sentence's final word while it settles the
punctuation — and it remains a hypothesis (PROJECT_STATE §10, L-28). No test
should encode a cause nobody has observed.

**When this file starts failing**, the defect's shape has changed. That is
expected the day L-28 is fixed. Update `PROJECT_STATE.md` §10 and the numbers
here in the same change; do not delete the file to make the suite green.

Evidence: `docs/slice4-last-test-report.json`, produced 2026-09-08 on Apple
silicon. Nothing here runs a model — it reads the committed report, which is
what makes a hardware-only finding testable in a Linux sandbox at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mosaique.transcript.segmenter import DEFAULT_SILENCE_MS

REPORT = Path(__file__).resolve().parents[3] / "docs" / "slice4-last-test-report.json"

# Measured on the 2026-09-08 report. Both are characterizations of a defect,
# not targets: the correct value for ORPHAN_COUNT is 0.
TOTAL_SEGMENTS = 30
ORPHAN_COUNT = 8
# The longest gap in the audio before any orphan. Well under DEFAULT_SILENCE_MS,
# which is the whole point: silence cannot explain these closes.
MAX_ACOUSTIC_GAP_MS = 560


def _segments() -> list[dict[str, Any]]:
    return json.loads(REPORT.read_text(encoding="utf-8"))["segments"]


def _is_orphan(segment: dict[str, Any]) -> bool:
    """A sentence's final word, alone, in its own very short segment."""
    text = segment["text"].strip()
    return segment["duration_ms"] <= 400 and text.endswith(".") and len(text.split()) <= 2


@pytest.fixture(scope="module")
def segments() -> list[dict[str, Any]]:
    if not REPORT.exists():  # pragma: no cover - the report is committed
        pytest.skip(f"validation report missing: {REPORT}")
    return _segments()


def test_the_report_is_the_one_these_numbers_were_measured_from(segments):
    """Guards the constants below against being compared to a different run."""
    assert len(segments) == TOTAL_SEGMENTS


def test_the_orphaned_final_word_defect_is_still_present(segments):
    """L-28. Deferred deliberately; this is what deferred looks like.

    A failure here means the count moved. If it moved to zero, L-28 is fixed —
    say so in `PROJECT_STATE.md` §10 rather than only here.
    """
    orphans = [s for s in segments if _is_orphan(s)]

    assert len(orphans) == ORPHAN_COUNT, (
        f"L-28 changed shape: {len(orphans)} orphaned final words, expected "
        f"{ORPHAN_COUNT}. If this is a fix, update PROJECT_STATE.md §10 too."
    )


def test_no_orphan_can_be_explained_by_silence_in_the_audio(segments):
    """The half of L-28 that *is* established, and the reason it is a defect.

    Each orphan is preceded by a real gap far shorter than the threshold that
    closes a segment, so the close came from somewhere other than the
    recording. This is the assertion to keep if the count above ever churns.
    """
    gaps = []
    previous = None
    for segment in segments:
        if _is_orphan(segment) and previous is not None:
            gaps.append(segment["start_ms"] - previous["end_ms"])
        previous = segment

    assert gaps, "expected at least one orphan preceded by another segment"
    assert max(gaps) == MAX_ACOUSTIC_GAP_MS
    assert max(gaps) < DEFAULT_SILENCE_MS, (
        "if the acoustic gaps now reach the silence threshold, these closes "
        "are ordinary silence and L-28's diagnosis needs revisiting"
    )


def test_the_orphans_are_sentence_ends_rather_than_scattered_noise(segments):
    """Every orphan ends a sentence, and the segment before it does not.

    This is what makes L-28 a systematic boundary defect rather than a handful
    of odd short segments — and it is the property Slice 5 must not build
    around, since a decision citing `tous.` as evidence is the visible symptom.
    """
    by_index = {s["sequence"]: s for s in segments}
    for segment in segments:
        if not _is_orphan(segment):
            continue
        preceding = by_index.get(segment["sequence"] - 1)
        assert preceding is not None
        assert not preceding["text"].rstrip().endswith((".", "!", "?")), (
            f"segment {preceding['sequence']} already ended a sentence, so "
            f"segment {segment['sequence']} is not an orphaned final word"
        )
