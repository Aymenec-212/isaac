"""What a segment actually says, once a human has corrected it (Slice 6R item 7).

**One definition, used by everything that reads a transcript.** The review page,
`?q=` search, and the summarizer's prompt all need the same answer to "what are
this segment's words, and whose are they" — and the answer stopped being simply
`segment.text` when Q9 put corrections in scope.

This module exists because the alternative has already bitten this project once.
L-35 was a value computed correctly in one place and read by nobody, because two
components each held their own idea of the same fact. A correction visible on
screen but absent from the prompt would be the same failure wearing different
clothes: the summary would quietly describe words the reader can no longer see.

It lives in `transcript/` rather than beside the API on purpose. `jobs/` and
`intelligence/` are downstream of the ingress and may not import a transport
(blueprint D-04, enforced by `tests/unit/test_architecture.py`), so the one place
both the route and the processor can reach is here.

**The raw values are never mutated.** These functions *read* a correction if one
exists and fall back to what the ASR produced. `segment.text` and `segment.words`
keep the model's output for good, which is what keeps L-28's shape, the 1.43% WER
and every `[measure]` row in §8 checkable after the fact.
"""

from __future__ import annotations

from typing import Protocol


class CorrectableSegment(Protocol):
    """A segment row, with the correction columns migration 0002 added."""

    participant_id: str
    text: str
    corrected_text: str | None
    corrected_participant_id: str | None


def effective_text(segment: CorrectableSegment) -> str:
    """The words to show, search and summarize: the correction, else the model's.

    An empty-string correction is honoured rather than treated as absent — the
    route refuses blank text, so a stored empty value would mean something
    deliberate. `is None` rather than falsiness is the difference.
    """
    return segment.text if segment.corrected_text is None else segment.corrected_text


def effective_participant_id(segment: CorrectableSegment) -> str:
    """Who said it, after any reattribution.

    On a single shared microphone this is the likelier of the two errors (L-2),
    and getting it wrong in the summary attributes someone's commitment to
    somebody else.
    """
    return segment.corrected_participant_id or segment.participant_id


def is_corrected(segment: CorrectableSegment) -> bool:
    """Whether a human has touched this segment at all."""
    return segment.corrected_text is not None or segment.corrected_participant_id is not None
