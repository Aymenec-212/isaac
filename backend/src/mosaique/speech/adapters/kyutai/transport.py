"""The port `moshi_server` talks through, declared where the adapter lives.

`test_architecture.py` forbids anything under `speech/` from importing a
transport library, and it is right to: blueprint D-04's rule is that the layers
below the ingress must not know how bytes move. A `moshi-server` client needs a
WebSocket, so the socket itself lives outside this package — in
`mosaique/asr_runtime/` — and is injected.

The Protocol deals in decoded messages rather than bytes on purpose. Framing is
msgpack, which is another dependency the adapter has no business holding, and
keeping it on the far side means the protocol logic in `moshi_server.py` is a
pure translation from dicts to `ASREvent`s — testable against a fake transport,
with no server, no CUDA and no network.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

Message = dict[str, Any]


class TransportClosed(RuntimeError):
    """The far end went away. The caller decides whether to reconnect."""


@runtime_checkable
class MoshiTransport(Protocol):
    """One connection to an `asr-runtime` process."""

    async def connect(self) -> None: ...

    async def send(self, message: Message) -> None: ...

    async def receive(self) -> Message:
        """Next message. Raises `TransportClosed` when the peer hangs up."""
        ...

    async def close(self) -> None: ...
