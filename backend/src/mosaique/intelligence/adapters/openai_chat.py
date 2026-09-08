"""OpenAI chat-completions behind `LLMProvider` (tech spec 12.2, Q2).

Nothing here opens a socket. The adapter is handed a `JsonTransport` and does
one job: turn our `complete_json(system, user, schema, deadline)` contract into
the request body OpenAI expects, and turn what comes back into a dict — or into
an error our processor already knows how to retry.

That split is deliberate and mirrors `MoshiServerBackend`: the vendor's wire
format is a translation problem and gets unit tests, while the HTTP client is a
plumbing problem and lives in `llm_runtime/`. It is also the only reason this
module can be exercised without spending credits.

**Structured outputs, not "please return JSON".** The request pins
`response_format={"type": "json_schema", ..., "strict": true}` so the model is
constrained during decoding rather than asked nicely afterwards. `schema.py`
still validates the result: strict mode guarantees the *shape*, and cannot
guarantee that `evidence_segment_ids` name segments that were really spoken.
Those are different claims and only the second one catches a hallucination.

Two OpenAI-specific quirks the schema has to survive, both handled by
`strictified()` below rather than by weakening `MeetingIntelligence`:

* strict mode requires `additionalProperties: false` on every object;
* strict mode requires every property to appear in `required`, so an optional
  field has to be expressed as a nullable type instead.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

DEFAULT_MODEL = "gpt-4o-mini"
SCHEMA_NAME = "meeting_intelligence"


class LLMTransportError(Exception):
    """The call did not produce a usable response.

    One exception type for every transport-shaped failure, because the job
    processor's retry policy does not care which one happened — it counts
    attempts and backs off. `retryable` exists for the one distinction that
    does matter: a 401 will fail identically three times and burn a meeting's
    outputs to learn nothing.
    """

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@runtime_checkable
class JsonTransport(Protocol):
    """POST a JSON body, get a JSON body back. Injected, never constructed here."""

    async def post_json(
        self, path: str, body: dict[str, Any], *, timeout_s: float
    ) -> dict[str, Any]: ...


def strictified(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a Pydantic JSON schema into one OpenAI strict mode accepts.

    Pydantic emits `required` listing only fields without defaults, and omits
    `additionalProperties`. Strict mode wants the opposite of both. Rewriting
    here keeps `MeetingIntelligence` written for our contract instead of bent
    around one vendor's decoder — the same reason the ASR adapter translates
    `moshi-server`'s messages rather than reshaping `WordEvent`.

    `$defs`/`$ref` are walked too: `ActionItem` and `EvidenceBacked` arrive as
    references, and an untouched definition fails the whole request.
    """
    out: dict[str, Any] = json.loads(json.dumps(schema))  # deep copy; schemas are small

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties", {})
            node["additionalProperties"] = False
            # Every property must be required; optionality becomes nullability.
            node["required"] = list(properties)
            for name, prop in properties.items():
                if name in _OPTIONAL_FIELDS:
                    _make_nullable(prop)
        for value in node.values():
            walk(value)

    walk(out)
    return out


# Fields `MeetingIntelligence` allows to be absent. Strict mode has no notion of
# "absent", so they are sent as nullable and Pydantic reads null back as None.
_OPTIONAL_FIELDS = {"owner_participant_id", "owner_text", "due_text"}


def _make_nullable(prop: dict[str, Any]) -> None:
    """Express `str | None` the way strict mode requires: an explicit union.

    Pydantic already emits `anyOf` for optional fields, so in practice this is
    a no-op guard for the shapes it does not.
    """
    if "anyOf" in prop or "$ref" in prop:
        return
    declared = prop.get("type")
    if declared is None:
        return
    if isinstance(declared, str):
        prop["type"] = [declared, "null"]
    elif "null" not in declared:
        prop["type"] = [*declared, "null"]


class OpenAIChatProvider:
    """`LLMProvider` over OpenAI's `/chat/completions`."""

    def __init__(
        self,
        transport: JsonTransport,
        *,
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 4096,
    ) -> None:
        self._transport = transport
        self._model = model
        self._max_output_tokens = max_output_tokens

    @property
    def model_name(self) -> str:
        """Recorded on `MeetingOutputs.llm_model`.

        The same reasoning as `Meeting.asr_version` (ADR-13 §3): a summary
        produced by one model is not evidence about another, and without this
        written down beside the output the distinction is lost after the fact.
        """
        return f"openai/{self._model}"

    async def complete_json(
        self, system: str, user: str, schema: dict[str, Any], deadline_s: float
    ) -> dict[str, Any]:
        body = {
            "model": self._model,
            "max_completion_tokens": self._max_output_tokens,
            # Determinism is worth more than variety here: two runs over the
            # same transcript disagreeing would make A-6's rejection rate
            # unmeasurable.
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": SCHEMA_NAME,
                    "strict": True,
                    "schema": strictified(schema),
                },
            },
        }
        payload = await self._transport.post_json("/chat/completions", body, timeout_s=deadline_s)
        return _content_of(payload)


def _content_of(payload: dict[str, Any]) -> dict[str, Any]:
    """Dig the JSON object out of a chat completion, or say why we cannot.

    Every failure below is raised rather than returned as an empty summary. A
    meeting with no outputs is visibly incomplete and gets retried; a meeting
    with a blank summary looks finished and is not.
    """
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMTransportError(f"response carried no choices: {sorted(payload)}")

    choice = choices[0]
    if choice.get("finish_reason") == "length":
        # Truncated JSON never parses, so this would otherwise surface as a
        # confusing decode error three times over.
        raise LLMTransportError(
            "model hit the output token cap before closing the JSON object; "
            "raise llm_max_output_tokens or chunk the transcript",
            retryable=False,
        )

    message = choice.get("message") or {}
    if message.get("refusal"):
        raise LLMTransportError(f"model refused: {message['refusal']}", retryable=False)

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMTransportError("response carried no message content")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMTransportError(f"response content was not JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise LLMTransportError(f"response content was {type(parsed).__name__}, not an object")
    return parsed
