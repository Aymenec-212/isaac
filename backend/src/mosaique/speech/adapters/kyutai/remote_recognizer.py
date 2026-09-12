"""Bounded readiness/admission for one app process and the pinned two-slot server."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace

from mosaique.speech.adapters.kyutai.moshi_server import MoshiServerBackend, MoshiSessionError
from mosaique.speech.adapters.kyutai.session import KyutaiRecognizer, KyutaiSession
from mosaique.speech.interfaces import (
    SILENCE_FRAME,
    ASRHealth,
    ASRSessionConfig,
    RecognizerReadiness,
)


class RemoteSession(KyutaiSession):
    def __init__(self, backend: MoshiServerBackend) -> None:
        super().__init__(backend)
        self._remote = backend

    def health(self) -> ASRHealth:
        health = super().health()
        return replace(health, healthy=health.healthy and not self._remote.closed)


class RemoteKyutaiRecognizer(KyutaiRecognizer):
    def __init__(
        self,
        factory: Callable[[], MoshiServerBackend],
        *,
        cache_s: float = 3.0,
        probe_timeout_s: float = 1.5,
    ) -> None:
        super().__init__(factory)
        self._factory = factory
        self._active: list[MoshiServerBackend] = []
        self._lock = asyncio.Lock()
        self._cached: tuple[float, RecognizerReadiness] | None = None
        self._cache_s = cache_s
        # Leave one second for WebSocket cleanup under the HTTP probe's 3s guard.
        self._probe_timeout_s = probe_timeout_s

    async def preload(self) -> None:
        # Do not make application liveness contingent on GPU availability.
        await self.readiness()

    def _prune(self) -> None:
        self._active = [backend for backend in self._active if not backend.closed]

    async def open_session(self, cfg: ASRSessionConfig) -> KyutaiSession:
        async with self._lock:
            self._prune()
            self._cached = None
            if len(self._active) >= 2:
                raise MoshiSessionError("ASR_CAPACITY_EXHAUSTED", "two ASR slots already reserved")
            backend = self._factory()
            session = RemoteSession(backend)
            try:
                await session.start()
            except BaseException:
                await backend.close()
                raise
            self._active.append(backend)
            self._identity = session.identity
            return session

    async def readiness(self) -> RecognizerReadiness:
        async with self._lock:
            self._prune()
            if self._active:
                # Never steal a free slot or open a third connection for health.
                self._cached = None
                if len(self._active) >= 2:
                    return RecognizerReadiness("not_ready", "ASR capacity occupied (2/2)")
                if all(backend.progressing for backend in self._active):
                    return RecognizerReadiness(
                        "ready", "active inference progressing; one local slot free"
                    )
                return RecognizerReadiness("not_ready", "active inference has no recent progress")
            now = time.monotonic()
            if self._cached is not None and now - self._cached[0] < self._cache_s:
                return self._cached[1]
            backend = self._factory()
            try:
                async with asyncio.timeout(self._probe_timeout_s):
                    await backend.start(lambda event: None)
                    await backend.push(SILENCE_FRAME)
                    await backend.flush()
                    if backend.processed_frames == 0:
                        raise MoshiSessionError(
                            "ASR_NO_PROGRESS", "probe marker without inference progress"
                        )
                result = RecognizerReadiness(
                    "ready", "Ready, inference progress and tail marker observed"
                )
            except (MoshiSessionError, RuntimeError, TimeoutError):
                result = RecognizerReadiness(
                    "not_ready", "remote ASR probe failed; inspect operator diagnostics"
                )
            finally:
                await backend.close()
            self._cached = (time.monotonic(), result)
            return result
