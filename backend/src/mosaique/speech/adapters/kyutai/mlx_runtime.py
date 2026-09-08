"""Kyutai STT on MLX, in this process, on a worker thread.

This is the only module in the codebase that imports a model library, and
`test_architecture.py` fails the build if that ever stops being true.

Three facts from Spike B1 shape everything here.

**One session at a time.** Loading the weights took 284 s on the machine B1 ran
on, so they are loaded once per process and cached. But `LmGen` carries the
per-stream KV cache, and two streams sharing one `Lm` would interleave their
caches and corrupt both transcripts silently. Rather than risk that, a second
concurrent MLX session is refused with a clear error. Slice 4 is a single-stream
slice by design; concurrency on a real serving runtime is Spike B2's question
(A-3), and `moshi_server` is the backend that answers it.

**Inference blocks, and it is not fast.** A step costs ~59 ms at the median
against an 80 ms budget — 1.24x realised, MARGINAL. Running that on the event
loop would stall every other participant, the gateway and the ping handler for
three quarters of every frame interval, so the model runs on a dedicated worker
thread and events come back with `call_soon_threadsafe`.

**`flush()` is not the D-05 trick here.** D-05 assumed the runtime processes
several times faster than real time, so a flush could catch up instantly. At
1.24x there is nothing to catch up with: A-12 is answered negatively for MLX.
So `flush()` does the only thing left — pushes the delay's worth of silence and
waits for the worker to drain it — and segment-close latency on MLX reverts to
roughly the model delay, as B1 predicted it would.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mosaique.speech.adapters.kyutai.backend import EventSink
from mosaique.speech.adapters.kyutai.identity import mlx_identity
from mosaique.speech.adapters.kyutai.pieces import PieceAssembler
from mosaique.speech.interfaces import (
    FRAME_DURATION_MS,
    SAMPLES_PER_FRAME,
    ASRErrorEvent,
    AsrIdentity,
)

log = logging.getLogger(__name__)

DEFAULT_HF_REPO = "kyutai/stt-1b-en_fr-mlx"

# Upstream `stt_from_file_mlx.py` skips these two ids: padding and epad. Most
# steps in real speech are one of them — 663 of B1's 825.
PADDING_TOKEN_IDS = frozenset({0, 3})

# Mimi is built with 32 codebooks in upstream's script regardless of what the
# config declares generated; mirrored rather than second-guessed.
MIMI_CODEBOOKS = 32

# Fallback only. B1 read 500 ms from `config.stt_config.audio_delay_seconds`,
# and the loader below prefers whatever the build actually declares.
FALLBACK_DELAY_MS = 500


class MlxUnavailable(RuntimeError):
    """MLX could not be used here, with a reason a human can act on."""


@dataclass(frozen=True)
class _Weights:
    """Everything loaded once per process and shared by every session."""

    model: Any
    audio_tokenizer: Any
    text_tokenizer: Any
    identity: AsrIdentity
    delay_ms: int
    config: dict[str, Any]


# Keyed by repository, because a process could be pointed at the `-candle`
# weights for their VAD heads without wanting the `-mlx` ones evicted.
_weights: dict[str, _Weights] = {}
_weights_lock = threading.Lock()
# Held for the lifetime of a session, not just of a call: it is the thing that
# makes "one stream at a time" true rather than merely intended.
_session_in_use = threading.Lock()


def _delay_ms_from_config(config: dict[str, Any]) -> int:
    """Read the delay the build declares; fall back loudly, never silently."""
    stt = config.get("stt_config")
    if isinstance(stt, dict):
        seconds = stt.get("audio_delay_seconds")
        if isinstance(seconds, (int, float)):
            return int(round(float(seconds) * 1000))
    log.warning("mlx_delay_not_declared_using_fallback", extra={"fallback_ms": FALLBACK_DELAY_MS})
    return FALLBACK_DELAY_MS


def load_weights(hf_repo: str = DEFAULT_HF_REPO) -> _Weights:
    """Load the model once per process. Blocking, and slow the first time.

    The sequence is copied from `moshi_mlx`'s own `stt_from_file_mlx.py` rather
    than invented, which is also why the dependency is pinned: deviating would
    mean measuring something upstream does not ship.
    """
    with _weights_lock:
        cached = _weights.get(hf_repo)
        if cached is not None:
            return cached
        try:
            import json

            import mlx.core as mx
            import mlx.nn as nn
            import sentencepiece
            from huggingface_hub import hf_hub_download
            from moshi_mlx import models
        except ImportError as exc:  # pragma: no cover - platform dependent
            raise MlxUnavailable(
                "MLX is not installed. It is macOS/arm64 only; install it with "
                '`uv pip install -e ".[mlx]"` on Apple silicon, or set '
                "MOSAIQUE_ASR_RUNTIME=fake."
            ) from exc

        config_path = hf_hub_download(hf_repo, "config.json")
        config: dict[str, Any] = json.loads(Path(config_path).read_text(encoding="utf-8"))
        mimi_weights = hf_hub_download(hf_repo, config["mimi_name"])
        moshi_name = config.get("moshi_name", "model.safetensors")
        moshi_weights = hf_hub_download(hf_repo, moshi_name)
        tokenizer_path = hf_hub_download(hf_repo, config["tokenizer_name"])

        lm_config = models.LmConfig.from_config_dict(config)
        model = models.Lm(lm_config)
        model.set_dtype(mx.bfloat16)
        if moshi_weights.endswith(".q4.safetensors"):
            nn.quantize(model, bits=4, group_size=32)
        elif moshi_weights.endswith(".q8.safetensors"):
            nn.quantize(model, bits=8, group_size=64)
        if hf_repo.endswith("-candle"):
            model.load_pytorch_weights(moshi_weights, lm_config, strict=True)
        else:
            model.load_weights(moshi_weights, strict=True)

        text_tokenizer = sentencepiece.SentencePieceProcessor(tokenizer_path)
        audio_tokenizer = models.mimi.Mimi(models.mimi_202407(MIMI_CODEBOOKS))
        audio_tokenizer.load_pytorch_weights(str(mimi_weights), strict=True)
        model.warmup()

        loaded = _Weights(
            model=model,
            audio_tokenizer=audio_tokenizer,
            text_tokenizer=text_tokenizer,
            identity=mlx_identity(hf_repo, moshi_name, revision=_revision_of(moshi_weights)),
            delay_ms=_delay_ms_from_config(config),
            config=config,
        )
        _weights[hf_repo] = loaded
        return loaded


def _revision_of(path: str) -> str | None:
    parts = Path(path).parts
    if "snapshots" in parts:
        index = parts.index("snapshots")
        if index + 1 < len(parts):
            return parts[index + 1]
    return None


class MlxBackend:
    """One MLX stream. Owns a worker thread for the lifetime of the session."""

    def __init__(self, *, hf_repo: str = DEFAULT_HF_REPO, max_steps: int = 8192) -> None:
        self._hf_repo = hf_repo
        self._max_steps = max_steps
        self._weights: _Weights | None = None
        self._gen: Any = None
        self._frames: queue.Queue[bytes | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._emit: EventSink | None = None
        self._processed = 0
        self._assembler: PieceAssembler | None = None
        self._holds_session_lock = False
        self._drained = threading.Event()
        self._drained.set()

    # ---- KyutaiBackend ---------------------------------------------------

    @property
    def identity(self) -> AsrIdentity:
        if self._weights is None:
            return mlx_identity(self._hf_repo, "model.safetensors")
        return self._weights.identity

    @property
    def delay_ms(self) -> int:
        return FALLBACK_DELAY_MS if self._weights is None else self._weights.delay_ms

    @property
    def emits_end_of_turn(self) -> bool:
        """False, measured. The `-mlx` weights carry no VAD heads (B1 §4)."""
        return False

    @property
    def processed_frames(self) -> int:
        return self._processed

    async def preload(self) -> None:
        """Fill the weights cache before any meeting needs it.

        B1 measured 284 s to load. Paying that inside `open_session` would
        block the ingress event loop for minutes while a participant's frames
        pile up behind it and their socket looks dead, so the app-server does it
        at startup instead and simply takes longer to come up.
        """
        await asyncio.to_thread(load_weights, self._hf_repo)

    async def start(self, emit: EventSink) -> None:
        if not _session_in_use.acquire(blocking=False):
            raise MlxUnavailable(
                "the MLX runtime serves one stream at a time in this process; a second "
                "participant would interleave KV caches and corrupt both transcripts. "
                "Use MOSAIQUE_ASR_RUNTIME=moshi_server for concurrent streams (A-3)."
            )
        self._holds_session_lock = True
        self._loop = asyncio.get_running_loop()
        self._emit = emit
        # Loading blocks for minutes on a cold cache; keep the event loop alive.
        self._weights = await asyncio.to_thread(load_weights, self._hf_repo)
        self._assembler = PieceAssembler(delay_ms=self._weights.delay_ms)
        self._gen = await asyncio.to_thread(self._new_gen)
        self._worker = threading.Thread(target=self._run, name="mlx-asr", daemon=True)
        self._worker.start()

    def _new_gen(self) -> Any:
        from moshi_mlx import models, utils

        assert self._weights is not None
        config = self._weights.config.get("lm_gen_config", {})
        return models.LmGen(
            model=self._weights.model,
            max_steps=self._max_steps,
            text_sampler=utils.Sampler(
                top_k=int(config.get("top_k_text", 25)), temp=float(config.get("temp_text", 0.0))
            ),
            audio_sampler=utils.Sampler(
                top_k=int(config.get("top_k", 250)), temp=float(config.get("temp", 0.8))
            ),
            check=False,
        )

    async def push(self, pcm: bytes) -> None:
        self._drained.clear()
        self._frames.put(pcm)

    async def flush(self) -> None:
        """Push the model delay's worth of silence, then wait for the worker.

        Not the D-05 accelerated catch-up: B1 measured 1.24x realised, so there
        is no spare throughput to catch up *with*, and A-12 is negative for this
        runtime. What this does instead is stop the last words of a meeting from
        being lost inside the delay — worth doing, but it costs roughly the
        delay rather than saving it.
        """
        silence = b"\x00" * (SAMPLES_PER_FRAME * 2)
        for _ in range(-(-self.delay_ms // FRAME_DURATION_MS)):
            await self.push(silence)
        await asyncio.to_thread(self._drained.wait, 30.0)
        if self._assembler is not None:
            for event in self._assembler.flush():
                self._publish(event)

    async def close(self) -> None:
        if self._worker is not None:
            self._frames.put(None)
            await asyncio.to_thread(self._worker.join, 10.0)
            self._worker = None
        self._release()

    def _release(self) -> None:
        if self._holds_session_lock:
            self._holds_session_lock = False
            _session_in_use.release()

    # ---- worker thread ---------------------------------------------------

    def _run(self) -> None:
        """Consume frames, run the model, marshal events back to the loop."""
        try:
            import mlx.core as mx

            assert self._weights is not None
            while True:
                pcm = self._frames.get()
                if pcm is None:
                    return
                block = mx.array(_to_float32(pcm)).reshape(1, 1, -1)
                codes = self._weights.audio_tokenizer.encode_step(block).transpose(0, 2, 1)
                token = self._gen.step(codes[0])
                token_id = int(token[0].item())
                step = self._processed
                self._processed += 1
                if self._frames.empty():
                    self._drained.set()
                if token_id in PADDING_TOKEN_IDS:
                    continue
                piece = str(self._weights.text_tokenizer.id_to_piece(token_id))
                assert self._assembler is not None
                for event in self._assembler.on_piece(step, piece):
                    self._publish(event)
        except Exception as exc:  # pragma: no cover - needs the model
            log.exception("mlx_worker_failed")
            self._publish(
                ASRErrorEvent(code="ASR_RUNTIME_FAILED", message=type(exc).__name__, fatal=True)
            )
            self._drained.set()

    def _publish(self, event: Any) -> None:
        """Hand an event to the event loop. Safe from the worker thread."""
        if self._loop is None or self._emit is None:
            return
        emit = self._emit
        self._loop.call_soon_threadsafe(emit, event)


def _to_float32(pcm: bytes) -> Any:
    import numpy as np

    return np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
