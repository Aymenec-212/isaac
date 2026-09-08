"""Kyutai-specific identity parsing (ADR-13 consequence 3).

`AsrIdentity` itself is product-neutral and lives in `speech/interfaces`. What
is Kyutai's own is how to read the three fields out of a Hugging Face
repository name and a weights filename, which is what this module does.

Pure. No model import, no I/O, no clock.
"""

from __future__ import annotations

from mosaique.speech.interfaces import AsrIdentity

# Runtime suffixes Kyutai puts on the repository name. They say which weights
# format a repo holds, not which runtime loads it — moshi_mlx happily loads the
# `-candle` weights — so they are stripped from the model id rather than being
# mistaken for the runtime.
REPO_SUFFIXES = ("-mlx", "-candle", "-pytorch")

QUANTIZATION_BY_SUFFIX = {".q4.safetensors": "q4", ".q8.safetensors": "q8"}
DEFAULT_QUANTIZATION = "bf16"


def model_id_from_repo(hf_repo: str) -> str:
    """`kyutai/stt-1b-en_fr-mlx` -> `kyutai/stt-1b-en_fr`."""
    for suffix in REPO_SUFFIXES:
        if hf_repo.endswith(suffix):
            return hf_repo[: -len(suffix)]
    return hf_repo


def quantization_from_weights(filename: str) -> str:
    """Mirror the loader: moshi_mlx infers bit width from the file name.

    Spike B1 ran on `model.safetensors` from the `-mlx` repository, which is
    bf16 — not the q4 the ADR used as its example. The example was a guess and
    this function is what the guess is replaced by.
    """
    lowered = filename.lower()
    for suffix, bits in QUANTIZATION_BY_SUFFIX.items():
        if lowered.endswith(suffix):
            return bits
    return DEFAULT_QUANTIZATION


def mlx_identity(hf_repo: str, weights_file: str, revision: str | None = None) -> AsrIdentity:
    return AsrIdentity(
        model_id=model_id_from_repo(hf_repo),
        runtime="mlx",
        quantization=quantization_from_weights(weights_file),
        revision=revision,
    )


def moshi_server_identity(hf_repo: str, quantization: str = DEFAULT_QUANTIZATION) -> AsrIdentity:
    """The server never reports what it loaded, so configuration declares it.

    Nothing in the wire protocol carries the weights' precision. Whoever
    deploys the server states it, and a wrong value produces a wrong
    `asr_version` — a labelling error, but a visible one, which is the best
    available from this side of the socket.
    """
    return AsrIdentity(
        model_id=model_id_from_repo(hf_repo), runtime="moshi-server", quantization=quantization
    )
