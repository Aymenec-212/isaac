"""The OpenAI adapter, with no OpenAI (tech spec 12.2, Q2).

Every test here runs against a fake transport. That is the point of the seam:
the vendor translation is the part that can be wrong in interesting ways, and
none of it should cost an API key or a network to check.

What is deliberately *not* claimed by this file: that OpenAI accepts the body
we build. Only a real call proves that, and it is recorded as unverified in
PROJECT_STATE §7 rather than implied here.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mosaique.intelligence import MeetingIntelligence, validate_outputs
from mosaique.intelligence.adapters.openai_chat import (
    LLMTransportError,
    OpenAIChatProvider,
    strictified,
)


class FakeTransport:
    """Records the request, returns a canned response."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        # `is None`, not `or`: an empty dict is a response we specifically want
        # to test, and `or` would silently swap in the valid one instead.
        self.payload = _completion(_valid_outputs()) if payload is None else payload
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    async def post_json(
        self, path: str, body: dict[str, Any], *, timeout_s: float
    ) -> dict[str, Any]:
        self.calls.append((path, body, timeout_s))
        return self.payload


def _valid_outputs() -> dict[str, Any]:
    return {
        "summary": "Le budget a été validé.",
        "key_points": ["Budget validé"],
        "decisions": [{"text": "Budget validé.", "evidence_segment_ids": ["seg-1"]}],
        "action_items": [
            {
                "text": "Livrer la maquette.",
                "owner_participant_id": None,
                "owner_text": "Équipe",
                "due_text": "vendredi",
                "evidence_segment_ids": ["seg-2"],
            }
        ],
        "open_questions": [],
    }


def _completion(content: dict[str, Any], *, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": json.dumps(content)},
            }
        ]
    }


def _objects(node: Any) -> list[dict[str, Any]]:
    """Every object-shaped node in a schema, `$defs` included."""
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_objects(item))
    elif isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            found.append(node)
        for value in node.values():
            found.extend(_objects(value))
    return found


# --- schema translation ---------------------------------------------------


def test_every_object_in_the_schema_is_closed_and_fully_required():
    """Both of strict mode's rules, checked on the schema we actually send.

    Asserted over `$defs` too, because `ActionItem` and `EvidenceBacked` arrive
    as references — and a definition left untouched fails the whole request
    while the top-level object looks perfectly correct.
    """
    strict = strictified(MeetingIntelligence.model_json_schema())

    objects = _objects(strict)
    assert len(objects) >= 3, "expected the root plus the two referenced definitions"
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj.get("properties", {}))


def test_optional_fields_survive_as_nullable_rather_than_being_dropped():
    """Strict mode has no "absent", so `owner_text` has to be sent as nullable.

    The failure this prevents is quiet: drop the field instead and every action
    item comes back with an owner the model invented, because it had no way to
    say it did not know.
    """
    strict = strictified(MeetingIntelligence.model_json_schema())
    action = next(obj for obj in _objects(strict) if "owner_text" in obj.get("properties", {}))
    assert "owner_text" in action["required"]

    prop = action["properties"]["owner_text"]
    rendered = json.dumps(prop)
    assert "null" in rendered, f"owner_text must admit null, got {rendered}"


def test_strictifying_does_not_mutate_the_caller_schema():
    """The processor passes `MeetingIntelligence.model_json_schema()` every run."""
    original = MeetingIntelligence.model_json_schema()
    before = json.dumps(original, sort_keys=True)
    strictified(original)
    assert json.dumps(original, sort_keys=True) == before


# --- request construction -------------------------------------------------


@pytest.mark.asyncio
async def test_the_request_pins_strict_structured_output_and_zero_temperature():
    transport = FakeTransport()
    provider = OpenAIChatProvider(transport, model="gpt-4o-mini", max_output_tokens=2048)

    await provider.complete_json("system", "user", MeetingIntelligence.model_json_schema(), 30.0)

    path, body, timeout = transport.calls[0]
    assert path == "/chat/completions"
    assert timeout == 30.0, "the job processor's deadline must reach the transport"
    assert body["model"] == "gpt-4o-mini"
    assert body["max_completion_tokens"] == 2048
    assert body["temperature"] == 0
    assert body["response_format"]["json_schema"]["strict"] is True
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_the_model_name_records_the_vendor_too():
    """`MeetingOutputs.llm_model` has to distinguish a fake run from a real one."""
    assert OpenAIChatProvider(FakeTransport(), model="gpt-4o-mini").model_name == (
        "openai/gpt-4o-mini"
    )


# --- response handling ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_well_formed_completion_passes_our_own_validator():
    """The round trip that matters: what the adapter returns is what §12.3 accepts."""
    provider = OpenAIChatProvider(FakeTransport())

    raw = await provider.complete_json("s", "u", MeetingIntelligence.model_json_schema(), 5.0)
    outputs = validate_outputs(raw, {"seg-1", "seg-2"})

    assert outputs.decisions[0].evidence_segment_ids == ["seg-1"]
    assert outputs.action_items[0].owner_participant_id is None


@pytest.mark.asyncio
async def test_a_truncated_response_says_so_instead_of_failing_to_parse():
    """`finish_reason=length` means the JSON was cut mid-object.

    Worth its own message: retried three times it would otherwise read as a
    mysterious decode error, when the actual fix is a bigger cap or chunking.
    """
    provider = OpenAIChatProvider(
        FakeTransport(_completion(_valid_outputs(), finish_reason="length"))
    )

    with pytest.raises(LLMTransportError) as caught:
        await provider.complete_json("s", "u", {}, 5.0)

    assert "token cap" in str(caught.value)
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_a_refusal_is_not_retried():
    payload = {"choices": [{"finish_reason": "stop", "message": {"refusal": "non"}}]}
    provider = OpenAIChatProvider(FakeTransport(payload))

    with pytest.raises(LLMTransportError) as caught:
        await provider.complete_json("s", "u", {}, 5.0)

    assert caught.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="no choices key"),
        pytest.param({"choices": []}, id="empty choices"),
        pytest.param(
            {"choices": [{"message": {"content": "  "}}]},
            id="blank content",
        ),
        pytest.param(
            {"choices": [{"message": {"content": "not json"}}]},
            id="content is not json",
        ),
        pytest.param(
            {"choices": [{"message": {"content": "[1, 2]"}}]},
            id="content is not an object",
        ),
    ],
)
async def test_a_malformed_response_raises_rather_than_returning_empty_outputs(payload):
    """None of these may become a blank summary.

    An empty summary looks like a finished meeting and never gets retried; a
    raised error is visible and does. That difference is the whole reason these
    five cases are enumerated instead of defaulted.
    """
    provider = OpenAIChatProvider(FakeTransport(payload))

    with pytest.raises(LLMTransportError):
        await provider.complete_json("s", "u", {}, 5.0)
