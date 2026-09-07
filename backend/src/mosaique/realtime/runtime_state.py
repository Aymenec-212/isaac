"""Process-wide registry wiring, initialised at startup."""

from __future__ import annotations

from pathlib import Path

from mosaique.realtime.gateway.broadcaster import SocketBroadcaster
from mosaique.realtime.sessions.registry import MeetingRegistry
from mosaique.speech.audio import AudioStore, LocalAudioStore
from mosaique.speech.interfaces import StreamingRecognizer

_registry: MeetingRegistry | None = None
_draining = False


def begin_drain() -> None:
    """Stop accepting new joins (tech spec 14.1, deployment row).

    Set before the registry is torn down, so a socket that arrives during a
    deploy is refused cleanly instead of joining a meeting that is about to
    stop existing.
    """
    global _draining
    _draining = True


def is_draining() -> bool:
    return _draining


def init_registry(
    *, recognizer: StreamingRecognizer, audio_root: Path, audio_store: AudioStore | None = None
) -> MeetingRegistry:
    global _registry
    _registry = MeetingRegistry(
        recognizer=recognizer,
        audio_store=audio_store or LocalAudioStore(audio_root),
        broadcaster=SocketBroadcaster(),
    )
    return _registry


def get_registry() -> MeetingRegistry:
    if _registry is None:
        raise RuntimeError("Meeting registry not initialised; call init_registry()")
    return _registry


async def shutdown_registry() -> None:
    global _registry, _draining
    if _registry is not None:
        await _registry.close_sockets(code=1012)
        await _registry.shutdown()
    _registry = None
    _draining = False
