"""Meeting intelligence: provider seam, adapters, prompt, output schema."""

from mosaique.intelligence.adapters.openai_chat import (
    LLMTransportError,
    OpenAIChatProvider,
    strictified,
)
from mosaique.intelligence.provider import FakeLLMProvider, LLMProvider
from mosaique.intelligence.schema import (
    MeetingIntelligence,
    OutputValidationError,
    validate_outputs,
)

__all__ = [
    "FakeLLMProvider",
    "LLMProvider",
    "LLMTransportError",
    "MeetingIntelligence",
    "OpenAIChatProvider",
    "OutputValidationError",
    "strictified",
    "validate_outputs",
]
