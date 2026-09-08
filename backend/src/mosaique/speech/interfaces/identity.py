"""Which model, on which runtime, at which precision (ADR-13 consequence 3).

Product-neutral, and in `interfaces/` rather than in an adapter because
`ASRSession` declares it: every recognizer has to be able to say what produced
its words, or `Meeting.asr_version` cannot be filled in without the runtime
knowing which adapter it is talking to — which is the coupling the seam exists
to prevent.

The model name alone is not enough. An MLX-era transcript and a CUDA-era one
carry different quantization and different runtimes, so a WER measured on one
does not describe the other (A-16). Recording all three is what keeps that
distinction visible after the fact instead of lost.
"""

from __future__ import annotations

from dataclasses import dataclass

# `Meeting.asr_version` is String(80) in migration 0001.
ASR_VERSION_MAX_LENGTH = 80


@dataclass(frozen=True)
class AsrIdentity:
    model_id: str
    runtime: str
    quantization: str
    revision: str | None = None

    @property
    def asr_version(self) -> str:
        return f"{self.model_id}@{self.runtime}-{self.quantization}"

    def truncated(self, limit: int = ASR_VERSION_MAX_LENGTH) -> str:
        """What actually goes in the column, never long enough to fail a write."""
        return self.asr_version[:limit]


# The fake is an identity too. A transcript it produced must never be mistaken
# for one a model produced, and a NULL column would leave exactly that doubt.
FAKE_IDENTITY = AsrIdentity(model_id="fake/scripted", runtime="fake", quantization="none")
