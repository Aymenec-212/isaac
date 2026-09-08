"""The HTTP client for `OpenAIChatProvider`, kept out of `intelligence/`.

`asr_runtime/moshi_ws.py` exists because `speech/` may not import a socket.
This module exists for the same reason on the other axis: `intelligence/` is
downstream of the ingress, and a layer that summarizes a transcript has no
business knowing that the thing summarizing it is reachable over HTTP.

`test_architecture.py` holds the boundary, so the split survives someone
finding it convenient to `import httpx` one layer up.
"""

from __future__ import annotations

from typing import Any

import httpx

from mosaique.intelligence.adapters.openai_chat import LLMTransportError

# Statuses worth trying again. Everything else is a request that will fail the
# same way three times: a bad key, a missing model, a malformed body.
RETRYABLE_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class HttpJsonTransport:
    """`JsonTransport` over `httpx`, with the API key held here and nowhere else."""

    def __init__(self, base_url: str, *, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def post_json(
        self, path: str, body: dict[str, Any], *, timeout_s: float
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(
                    url,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise LLMTransportError(f"request timed out after {timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise LLMTransportError(f"request failed: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            raise LLMTransportError(
                # The body can echo transcript text back, and tech spec 13.3
                # says that does not go in logs. The status is what the
                # operator needs; the detail stays in the provider's dashboard.
                f"provider returned HTTP {response.status_code}",
                status=response.status_code,
                retryable=response.status_code in RETRYABLE_STATUSES,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMTransportError("provider returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise LLMTransportError(f"provider returned {type(payload).__name__}, not an object")
        return payload
