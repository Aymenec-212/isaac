"""Meeting intelligence output contract (tech spec 12.3).

`evidence_segment_ids` is required on every decision, action and open question,
and every id is checked against the segments that actually exist. This is what
makes a hallucinated action item *detectable* rather than plausible, and it is
the traceability the PRD asks for.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError


class EvidenceBacked(BaseModel):
    text: str = Field(min_length=1)
    evidence_segment_ids: list[str] = Field(min_length=1)


class ActionItem(EvidenceBacked):
    owner_participant_id: str | None = None
    owner_text: str | None = None
    due_text: str | None = None


class MeetingIntelligence(BaseModel):
    summary: str = Field(min_length=1)
    key_points: list[str] = Field(default_factory=list)
    decisions: list[EvidenceBacked] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    open_questions: list[EvidenceBacked] = Field(default_factory=list)


class OutputValidationError(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def validate_outputs(payload: dict[str, Any], known_segment_ids: set[str]) -> MeetingIntelligence:
    """Parse, then reject any evidence id that does not exist.

    Schema conformance alone is not enough: a model can return well-formed JSON
    citing segments that were never spoken.
    """
    try:
        parsed = MeetingIntelligence.model_validate(payload)
    except ValidationError as exc:
        raise OutputValidationError("schema", str(exc)) from exc

    cited: set[str] = set()
    for group in (parsed.decisions, parsed.action_items, parsed.open_questions):
        for item in group:
            cited.update(item.evidence_segment_ids)

    unknown = sorted(cited - known_segment_ids)
    if unknown:
        raise OutputValidationError(
            "unknown_evidence",
            f"{len(unknown)} evidence id(s) do not match any segment: {unknown[:3]}",
        )
    return parsed
