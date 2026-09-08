"""Turn configuration into a `StreamingRecognizer` (ADR-13, fail-fast).

The composition root for the ASR axis. It lives here rather than in
`speech/` because building the `moshi_server` runtime means constructing a
WebSocket, and `speech/` may not import one.
"""

from __future__ import annotations

from mosaique.asr_runtime.moshi_ws import MoshiWebSocketTransport
from mosaique.config.settings import Settings
from mosaique.observability.logging import get_logger
from mosaique.speech.adapters.fake import FakeRecognizer
from mosaique.speech.adapters.kyutai import KyutaiRecognizer, MoshiServerBackend
from mosaique.speech.interfaces import StreamingRecognizer

log = get_logger(__name__)


def build_recognizer(settings: Settings) -> StreamingRecognizer:
    """The one place that decides which runtime is in the path.

    Raises rather than falling back. A silent downgrade to the fake would put
    scripted French in a real meeting's transcript, and nothing downstream could
    tell — which is exactly the failure `Meeting.asr_version` exists to make
    impossible after the fact and this raise makes impossible in the first place.
    """
    runtime = settings.asr_runtime
    if runtime == "fake":
        log.info("asr_runtime_selected", runtime="fake")
        return FakeRecognizer()

    if runtime == "mlx":
        # Imported here, not at module scope: MLX is macOS/arm64 only and this
        # module is imported on every start, including in the Linux sandbox.
        from mosaique.speech.adapters.kyutai.mlx_runtime import MlxBackend

        repo = settings.asr_model_repo
        log.info("asr_runtime_selected", runtime="mlx", repo=repo)
        return KyutaiRecognizer(lambda: MlxBackend(hf_repo=repo))

    if runtime == "moshi_server":
        url = settings.asr_moshi_server_url
        if not url:  # pragma: no cover - the settings validator gets here first
            raise ValueError("asr_moshi_server_url is required for the moshi_server runtime")
        key = settings.asr_moshi_server_api_key
        quantization = settings.asr_moshi_server_quantization
        log.info("asr_runtime_selected", runtime="moshi_server", url=url)
        return KyutaiRecognizer(
            lambda: MoshiServerBackend(
                MoshiWebSocketTransport(url, api_key=key),
                quantization=quantization,
            )
        )

    raise ValueError(f"unknown asr_runtime {runtime!r}")
