"""MLX is deliberately single-stream; there is no concurrency escape hatch."""

import asyncio
import inspect
import threading
from types import SimpleNamespace

import pytest

from mosaique.speech.adapters.kyutai import mlx_runtime


def test_mlx_has_no_concurrency_bypass():
    assert "allow_concurrent_streams" not in inspect.signature(mlx_runtime.MlxBackend).parameters
    with pytest.raises(TypeError):
        mlx_runtime.MlxBackend(allow_concurrent_streams=True)


async def test_busy_mlx_refuses_a_second_stream_before_loading_weights(monkeypatch):
    import threading

    gate = threading.Lock()
    gate.acquire()
    monkeypatch.setattr(mlx_runtime, "_session_in_use", gate)
    backend = mlx_runtime.MlxBackend()
    with pytest.raises(mlx_runtime.MlxUnavailable, match="one stream at a time"):
        await backend.start(lambda event: None)
    await backend.close()
    assert gate.locked(), "a rejected participant must not release the owner's lock"
    gate.release()


async def test_owner_releases_the_single_stream_slot_once(monkeypatch):
    import threading

    gate = threading.Lock()
    gate.acquire()
    monkeypatch.setattr(mlx_runtime, "_session_in_use", gate)
    backend = mlx_runtime.MlxBackend()
    backend._holds_session_lock = True
    await backend.close()
    await backend.close()
    assert not gate.locked()


def stub_worker(monkeypatch):
    gate = threading.Lock()
    monkeypatch.setattr(mlx_runtime, "_session_in_use", gate)
    monkeypatch.setattr(mlx_runtime, "load_weights", lambda _: SimpleNamespace(delay_ms=500))
    monkeypatch.setattr(mlx_runtime.MlxBackend, "_new_gen", lambda _: object())
    return gate


async def test_cancelled_close_keeps_lock_until_worker_exits_then_releases(monkeypatch):
    gate = stub_worker(monkeypatch)
    release = threading.Event()
    monkeypatch.setattr(mlx_runtime.MlxBackend, "_run", lambda _: release.wait(2))
    backend = mlx_runtime.MlxBackend()
    await backend.start(lambda _: None)
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(backend.close(), 0.01)
        assert gate.locked()
        with pytest.raises(mlx_runtime.MlxUnavailable):
            await mlx_runtime.MlxBackend().start(lambda _: None)
    finally:
        release.set()
        await asyncio.to_thread(backend._worker.join, 2)
    assert not gate.locked()
    replacement = mlx_runtime.MlxBackend()
    await replacement.start(lambda _: None)
    await replacement.close()
    assert not gate.locked()


async def test_cancelled_initialization_releases_only_when_initialization_exits(monkeypatch):
    gate = stub_worker(monkeypatch)
    release = threading.Event()
    entered = threading.Event()

    def load(_):
        entered.set()
        release.wait(2)
        return SimpleNamespace(delay_ms=500)

    monkeypatch.setattr(mlx_runtime, "load_weights", load)
    backend = mlx_runtime.MlxBackend()
    task = asyncio.create_task(backend.start(lambda _: None))
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gate.locked()
    release.set()
    await asyncio.to_thread(backend._worker.join, 2)
    assert not gate.locked()


async def test_initialization_failure_does_not_leak_slot(monkeypatch):
    gate = stub_worker(monkeypatch)

    def fail(_):
        raise RuntimeError("initialization failed")

    monkeypatch.setattr(mlx_runtime.MlxBackend, "_new_gen", fail)
    backend = mlx_runtime.MlxBackend()
    with pytest.raises(RuntimeError, match="initialization failed"):
        await backend.start(lambda _: None)
    await backend.close()
    assert not gate.locked()
