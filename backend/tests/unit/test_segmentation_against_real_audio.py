"""The §9.3 thresholds, checked against the audio they were tuned on.

Slice 4's instruction was to tune the `[measure]` values against real French
audio rather than against the fake. This is what makes that claim checkable: it
replays the word timings Spike B1 measured — 64 s of one French speaker, 92
words — through the real `Segmenter` and asserts the sentences come out whole.

The fixture is the B1 machine report, committed at `docs/mosaique-b1-main/`.
Only the word timings are used, so nothing here needs a model, a GPU or a Mac,
and the test runs in the fast suite like everything else.

What it is *not*: evidence about any other speaker. n=1. The numbers it pins
are the ones in `PROJECT_STATE.md` §8, marked exactly as thinly as they deserve.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaique.speech.interfaces import WordEvent
from mosaique.transcript.segmenter import (
    DEFAULT_MAX_SEGMENT_MS,
    Segmenter,
    SegmentFinal,
)

B1_REPORT = Path(__file__).resolve().parents[3] / "docs" / "mosaique-b1-main" / "b1-report.json"

# The four sentences the speaker actually said, by their opening words. Written
# out rather than derived so that a regression changes this file visibly.
EXPECTED_OPENINGS = ("Alors bonjour,", "Ce que", "J'ai grandi", "Pas de voiture,")


@pytest.fixture(scope="module")
def b1_words() -> list[WordEvent]:
    if not B1_REPORT.is_file():
        pytest.skip(f"B1 report not present at {B1_REPORT}")
    report = json.loads(B1_REPORT.read_text(encoding="utf-8"))
    return [
        WordEvent(text=w["text"], start_ms=w["start_ms"], end_ms=w["end_ms"], confidence=None)
        for w in report["words"]
    ]


def run(words: list[WordEvent], segmenter: Segmenter) -> list[SegmentFinal]:
    """Feed words in order, ticking silence in stream time between them.

    The tick mirrors what `_read_events` does in the runtime: silence is judged
    against the recognizer's transcribed position (ADR-11), never a clock.
    """
    finals: list[SegmentFinal] = []
    for previous, word in zip([None, *words], words, strict=False):
        if previous is not None:
            finals += [e for e in segmenter.on_tick(word.start_ms) if isinstance(e, SegmentFinal)]
        finals += [e for e in segmenter.on_word(word) if isinstance(e, SegmentFinal)]
    finals += [e for e in segmenter.close_open() if isinstance(e, SegmentFinal)]
    return finals


def test_the_tuned_defaults_reproduce_the_speakers_four_sentences(b1_words):
    """The whole point of the retune, as one assertion."""
    finals = run(b1_words, Segmenter())

    assert len(finals) == 4
    for final, opening in zip(finals, EXPECTED_OPENINGS, strict=True):
        assert final.text.startswith(opening), f"{final.text[:40]!r} does not open with {opening!r}"


def test_the_old_700ms_threshold_split_phrases_that_were_not_finished(b1_words):
    """Why 700 ms had to go, pinned so it cannot drift back unnoticed.

    Six of the splits land inside a phrase — `endroits | familiers`,
    `à | Casablanca`, `crée | un` — because this speaker's largest mid-phrase
    pause is 1120 ms while their shortest real sentence break is 880 ms. The
    distributions overlap, so no silence threshold separates them, which is the
    finding the punctuation rule exists to answer.
    """
    finals = run(b1_words, Segmenter(silence_ms=700, close_on_sentence_end=False))

    assert len(finals) > 4
    broken = [f.text for f in finals if f.text.endswith(("endroits", "à", "crée"))]
    assert broken, "expected the old threshold to cut a phrase mid-way"


def test_silence_alone_cannot_do_the_job_at_any_threshold(b1_words):
    """No silence-only setting gets four segments: the evidence, as a test.

    Raise it far enough not to split `endroits | familiers` (1120 ms) and it has
    already stopped seeing the real break after `caractère.` (880 ms).
    """
    counts = {
        ms: len(run(b1_words, Segmenter(silence_ms=ms, close_on_sentence_end=False)))
        for ms in (700, 900, 1_000, 1_200, 1_500, 2_000)
    }

    assert 4 not in counts.values(), f"a silence-only threshold worked after all: {counts}"


def test_no_segment_reaches_the_duration_cap(b1_words):
    """The cap stays UNMEASURED, and this is what says so.

    Longest natural segment here is 12.7 s against a 15 s cap, so nothing in B1
    exercised it. If a future fixture makes this fail, the cap has finally been
    measured and §8 can say so.
    """
    finals = run(b1_words, Segmenter())

    longest = max(f.end_ms - f.start_ms for f in finals)
    assert longest < DEFAULT_MAX_SEGMENT_MS
    assert not any(f.reason == "max_duration" for f in finals)


def test_every_close_is_explained_by_punctuation(b1_words):
    """On MLX there is no end-of-turn event, so this is the only rule left.

    All four, including the last: the speaker's final word is `paysage.`, so
    the closing flush finds nothing left open. Silence never fired once in 64 s
    of speech, which is the same finding as the test above seen from the other
    side.
    """
    finals = run(b1_words, Segmenter())

    assert [f.reason for f in finals] == ["sentence_end"] * 4
