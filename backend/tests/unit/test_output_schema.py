"""Intelligence output validation (tech spec 12.3)."""

from __future__ import annotations

import pytest

from mosaique.intelligence.prompt import build_user_prompt, format_timestamp
from mosaique.intelligence.schema import OutputValidationError, validate_outputs

KNOWN = {"seg-1", "seg-2"}


def valid_payload(**overrides):
    payload = {
        "summary": "Résumé de la réunion.",
        "key_points": ["Budget validé"],
        "decisions": [{"text": "Budget validé.", "evidence_segment_ids": ["seg-1"]}],
        "action_items": [
            {
                "text": "Livrer la maquette.",
                "owner_text": "Sarah",
                "due_text": "vendredi",
                "evidence_segment_ids": ["seg-2"],
            }
        ],
        "open_questions": [],
    }
    payload.update(overrides)
    return payload


def test_valid_output_passes():
    parsed = validate_outputs(valid_payload(), KNOWN)
    assert parsed.summary.startswith("Résumé")
    assert parsed.decisions[0].evidence_segment_ids == ["seg-1"]


def test_unknown_evidence_id_is_rejected():
    """A hallucinated citation must be detectable, not merely well-formed."""
    payload = valid_payload(decisions=[{"text": "Inventé.", "evidence_segment_ids": ["seg-999"]}])
    with pytest.raises(OutputValidationError) as exc:
        validate_outputs(payload, KNOWN)
    assert exc.value.reason == "unknown_evidence"


def test_unknown_evidence_in_an_action_item_is_rejected():
    payload = valid_payload(action_items=[{"text": "Faire X.", "evidence_segment_ids": ["nope"]}])
    with pytest.raises(OutputValidationError):
        validate_outputs(payload, KNOWN)


def test_decision_without_any_evidence_is_rejected():
    payload = valid_payload(decisions=[{"text": "Sans preuve.", "evidence_segment_ids": []}])
    with pytest.raises(OutputValidationError) as exc:
        validate_outputs(payload, KNOWN)
    assert exc.value.reason == "schema"


def test_missing_summary_is_rejected():
    payload = valid_payload()
    del payload["summary"]
    with pytest.raises(OutputValidationError) as exc:
        validate_outputs(payload, KNOWN)
    assert exc.value.reason == "schema"


def test_prompt_marks_transcript_as_data_and_exposes_segment_ids():
    class Seg:
        def __init__(self, sid, pid, start, text):
            self.id, self.participant_id, self.start_ms, self.text = sid, pid, start, text
            # A real row carries these (migration 0002) and the prompt reads the
            # effective values through them; an uncorrected segment has both None.
            self.corrected_text = None
            self.corrected_participant_id = None

    prompt = build_user_prompt([Seg("seg-1", "p1", 65_000, "Bonjour.")], {"p1": "Amina"})
    assert "<transcript>" in prompt and "</transcript>" in prompt
    assert "[seg-1] Amina (01:05): Bonjour." in prompt


def test_timestamp_formatting():
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(65_000) == "01:05"
    assert format_timestamp(3_600_000) == "60:00"
