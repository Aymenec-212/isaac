"""LLM provider seam and the deterministic stand-in (tech spec 12.2)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    async def complete_json(
        self, system: str, user: str, schema: dict[str, Any], deadline_s: float
    ) -> dict[str, Any]: ...

    @property
    def model_name(self) -> str: ...


class FakeLLMProvider:
    """Builds outputs from the transcript it is given, citing real segments.

    It is not a language model, but it exercises the whole contract honestly:
    the ids it cites are real, so the validator in `schema.py` is genuinely
    tested rather than trivially satisfied.
    """

    model_name = "fake-llm-v1"

    def __init__(self, *, fail_times: int = 0) -> None:
        self._fail_times = fail_times
        self.calls = 0

    async def complete_json(
        self, system: str, user: str, schema: dict[str, Any], deadline_s: float
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise RuntimeError("simulated provider failure")

        segment_ids = _segment_ids_from_prompt(user)
        first = segment_ids[:1]
        last = segment_ids[-1:] or first

        return {
            "summary": (
                "Réunion de suivi : le budget du trimestre a été validé et la "
                "livraison de la maquette a été fixée à vendredi."
            ),
            "key_points": [
                "Budget du trimestre validé",
                "Maquette attendue avant vendredi",
            ],
            "decisions": (
                [{"text": "Le budget du trimestre est validé.", "evidence_segment_ids": first}]
                if first
                else []
            ),
            "action_items": (
                [
                    {
                        "text": "Livrer la maquette avant vendredi.",
                        "owner_participant_id": None,
                        "owner_text": "Équipe produit",
                        "due_text": "vendredi",
                        "evidence_segment_ids": last,
                    }
                ]
                if last
                else []
            ),
            "open_questions": [],
        }


def _segment_ids_from_prompt(prompt: str) -> list[str]:
    """Read back the `[seg_id]` markers the prompt builder emitted."""
    ids: list[str] = []
    for line in prompt.splitlines():
        line = line.strip()
        if line.startswith("[") and "]" in line:
            ids.append(line[1 : line.index("]")])
    return ids
