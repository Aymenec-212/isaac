"""Turn configuration into an `LLMProvider` (Q2, fail-fast).

The composition root for the intelligence axis, deliberately the same shape as
`asr_runtime/factory.py`. It lives here rather than in `intelligence/` because
building the OpenAI provider means constructing an HTTP client, and
`intelligence/` may not import one.
"""

from __future__ import annotations

from mosaique.config.settings import Settings
from mosaique.intelligence.adapters.openai_chat import OpenAIChatProvider
from mosaique.intelligence.provider import FakeLLMProvider, LLMProvider
from mosaique.llm_runtime.http import HttpJsonTransport
from mosaique.observability.logging import get_logger

log = get_logger(__name__)


def build_llm_provider(settings: Settings) -> LLMProvider:
    """The one place that decides which provider is in the path.

    Raises rather than falling back, for the reason `build_recognizer` does:
    a silent downgrade to the fake would write invented French decisions into
    a real meeting's outputs, and `MeetingOutputs.llm_model` would be the only
    trace — after the fact, and only if someone looked.
    """
    provider = settings.llm_provider
    if provider == "fake":
        log.info("llm_provider_selected", provider="fake")
        return FakeLLMProvider()

    if provider == "openai":
        key = settings.llm_api_key
        if not key:  # pragma: no cover - the settings validator gets here first
            raise ValueError("llm_api_key is required for the openai provider")
        log.info(
            "llm_provider_selected",
            provider="openai",
            model=settings.llm_model,
            base_url=settings.llm_base_url,
        )
        return OpenAIChatProvider(
            HttpJsonTransport(settings.llm_base_url, api_key=key),
            model=settings.llm_model,
            max_output_tokens=settings.llm_max_output_tokens,
        )

    raise ValueError(f"unknown llm_provider {provider!r}")
