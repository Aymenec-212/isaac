"""Concrete transports to an `asr-runtime` process.

This package exists for one reason: blueprint D-04 forbids anything under
`speech/` from importing a transport library, and a `moshi-server` client needs
a WebSocket. So `speech/adapters/kyutai/transport.py` declares the port and the
socket that implements it lives out here, on the composition side of the seam.

That is the same shape as `MeetingIngress` — the layer that does the work
declares what it needs, and wiring supplies it — and it is what lets the
protocol translation in `moshi_server.py` be tested with no server, no CUDA and
no network.
"""

from mosaique.asr_runtime.factory import build_recognizer
from mosaique.asr_runtime.moshi_ws import MoshiWebSocketTransport

__all__ = ["MoshiWebSocketTransport", "build_recognizer"]
