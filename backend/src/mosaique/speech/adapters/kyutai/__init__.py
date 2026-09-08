"""Kyutai `stt-1b-en_fr` behind `StreamingRecognizer` (tech spec 9.2, ADR-13).

One model, three runtimes, chosen by configuration:

* `fake` lives elsewhere and carries Slices 1-3 and every test;
* `mlx` runs the model in this process on Apple silicon — development, and the
  runtime Spike B1 measured;
* `moshi_server` reaches a CUDA host over a WebSocket — deployment, and the
  only one that can answer A-3 and A-4.

Nothing outside this package imports a model library, and nothing inside it
imports a transport. Both halves of that are enforced by
`tests/unit/test_architecture.py`, which is why the `moshi_server` socket is
injected through `transport.MoshiTransport` rather than opened here.
"""

from mosaique.speech.adapters.kyutai.backend import EventSink, KyutaiBackend
from mosaique.speech.adapters.kyutai.backoff import delays
from mosaique.speech.adapters.kyutai.identity import (
    mlx_identity,
    model_id_from_repo,
    moshi_server_identity,
    quantization_from_weights,
)
from mosaique.speech.adapters.kyutai.moshi_server import MoshiServerBackend, pcm_to_floats
from mosaique.speech.adapters.kyutai.pieces import PieceAssembler
from mosaique.speech.adapters.kyutai.session import KyutaiRecognizer, KyutaiSession
from mosaique.speech.adapters.kyutai.transport import MoshiTransport, TransportClosed

__all__ = [
    "EventSink",
    "KyutaiBackend",
    "KyutaiRecognizer",
    "KyutaiSession",
    "MoshiServerBackend",
    "MoshiTransport",
    "PieceAssembler",
    "TransportClosed",
    "delays",
    "mlx_identity",
    "model_id_from_repo",
    "moshi_server_identity",
    "pcm_to_floats",
    "quantization_from_weights",
]
