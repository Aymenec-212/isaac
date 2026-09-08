# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "huggingface_hub",
#     "moshi_mlx==0.2.12",
#     "numpy",
#     "sentencepiece",
#     "sphn",
# ]
# ///
"""Spike B1 — measure `kyutai/stt-1b-en_fr-mlx` on Apple silicon.

    uv run --script backend/tools/spike_b1/probe.py path/to/fixture.wav

Answers exactly four questions and prints them as one pasteable block:

    1. does emitted text ever change after it is emitted        (X-14)
    2. realised speed factor, wall time vs. audio duration      (A-12, D-05)
    3. quantization and model identity                          (Meeting.asr_version)
    4. event shape: word text, word timestamps, end-of-turn     (spec 9.1, 9.3)

Two things about how this is put together, both deliberate.

**It is a PEP 723 script, not part of the backend project.** MLX is macOS/arm64
only; ADR-13 consequence 5 says its dependencies must never enter the backend's
dependency graph, or a Linux checkout stops installing. `uv run --script` builds
a throwaway environment from the header above and leaves `backend/pyproject.toml`
alone. It also pins `moshi_mlx` to the version whose loader this file mirrors,
because the loading sequence below is copied from that release's
`stt_from_file_mlx.py` rather than invented here.

**All the reasoning lives in `b1_analysis.py` and `b1_summary.py`, which import
nothing from MLX.** This file only drives the model and records what it did.
That is what lets the analysis be unit-tested in a sandbox with no GPU, which is
the whole division of labour this spike runs under: one person builds, another
measures.

The VAD pass is a second pass over the same audio against
`kyutai/stt-1b-en_fr-candle`, because that is the repository upstream reaches
for when `--vad` is set — the `-mlx` repository's weights do not carry the extra
heads. Its numbers are therefore a *different build* and are reported
separately, never merged with the first pass.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from b1_analysis import (  # noqa: E402
    FRAME_DURATION_MS,
    PADDING_TOKEN_IDS,
    SAMPLE_RATE_HZ,
    SAMPLES_PER_FRAME,
    ModelIdentity,
    SpeedReport,
    TokenEvent,
    VadReport,
    VadSample,
    analyse_retraction,
    analyse_vad,
    assemble_words,
    discover_delay_ms,
    discover_silence_prefix_ms,
    quantization_from_weights,
)
from b1_summary import Findings, render  # noqa: E402

DEFAULT_REPO = "kyutai/stt-1b-en_fr-mlx"
DEFAULT_VAD_REPO = "kyutai/stt-1b-en_fr-candle"

# Upstream appends two seconds of silence so the model's delayed output drains.
TRAILING_SILENCE_MS = 2_000

# Upstream reads head 2 and thresholds it at 0.5. We record every head and
# several thresholds, because picking the head and the threshold is exactly the
# `[measure]` decision Slice 4 has to make.
VAD_HEAD_INDEX = 2
VAD_THRESHOLDS = (0.3, 0.5, 0.7, 0.9)


# --------------------------------------------------------------------------
# Environment and model identity
# --------------------------------------------------------------------------


def _sysctl(key: str) -> str:
    try:
        done = subprocess.run(
            ["sysctl", "-n", key], capture_output=True, text=True, timeout=5, check=False
        )
        return done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def describe_environment() -> dict[str, str]:
    brand = _sysctl("machdep.cpu.brand_string") or platform.processor() or "unknown cpu"
    memory = _sysctl("hw.memsize")
    memory_gb = format(int(memory) / 1e9, ".0f") + " GB" if memory.isdigit() else "unknown"
    versions = []
    for name in ("moshi_mlx", "mlx", "sentencepiece", "sphn"):
        versions.append(name + " " + _version(name))
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script": "backend/tools/spike_b1/probe.py",
        "host": platform.platform() + " / " + platform.machine(),
        "cpu": brand + " / " + memory_gb,
        "python": platform.python_version(),
        "packages": ", ".join(versions),
    }


def _version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name.replace("_", "-"))
    except Exception:  # a missing version must not fail the run
        return "?"


def _revision_from_cache(path: str) -> str:
    parts = Path(path).parts
    if "snapshots" in parts:
        index = parts.index("snapshots")
        if index + 1 < len(parts):
            return parts[index + 1]
    return "unknown (not a huggingface cache path)"


def _blob_from_cache(path: str) -> str:
    """The hub stores blobs under their content hash and symlinks snapshots."""
    try:
        if os.path.islink(path):
            return Path(os.readlink(path)).name
    except OSError:
        pass
    return "unknown (not a symlink)"


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------


@dataclass
class Fixture:
    samples: Any
    fixture_ms: int
    pushed_ms: int
    frames: int
    channels_mixed: bool
    path: str
    silence_prefix_ms: int
    trailing_silence_ms: int


def load_fixture(path: Path, *, silence_prefix_ms: int, trailing_silence_ms: int) -> Fixture:
    """Read any format sphn can open, or the canonical raw PCM this repo uses.

    `.pcm` is accepted because that is what `tools/replay` fixtures are (tech
    spec 8.1: 24 kHz s16le mono), so the same recording can drive both this
    spike and the Slice 4 replay without being converted twice.
    """
    import numpy as np

    if path.suffix.lower() == ".pcm":
        raw = np.frombuffer(path.read_bytes(), dtype="<i2").astype("float32") / 32768.0
        wave = raw.reshape(1, -1)
        mixed = False
    else:
        import sphn

        data, _ = sphn.read(str(path), sample_rate=SAMPLE_RATE_HZ)
        wave = np.asarray(data, dtype="float32")
        if wave.ndim == 1:
            wave = wave.reshape(1, -1)
        mixed = bool(wave.shape[0] > 1)
        if mixed:
            # The gateway only ever sees mono (spec 8.1). Mixing here rather
            # than taking channel 0 keeps a stereo recording usable.
            wave = wave.mean(axis=0, keepdims=True)

    fixture_samples = int(wave.shape[-1])
    prefix = np.zeros((1, silence_prefix_ms * SAMPLE_RATE_HZ // 1000), dtype="float32")
    suffix = np.zeros((1, trailing_silence_ms * SAMPLE_RATE_HZ // 1000), dtype="float32")
    padded = np.concatenate([prefix, wave, suffix], axis=-1)
    frames = int(padded.shape[-1]) // SAMPLES_PER_FRAME
    return Fixture(
        samples=padded,
        fixture_ms=fixture_samples * 1000 // SAMPLE_RATE_HZ,
        pushed_ms=frames * FRAME_DURATION_MS,
        frames=frames,
        channels_mixed=mixed,
        path=str(path),
        silence_prefix_ms=silence_prefix_ms,
        trailing_silence_ms=trailing_silence_ms,
    )


def write_canonical_pcm(fixture_path: Path, out: Path) -> None:
    """Emit 24 kHz s16le mono so `tools/replay` can point at the same audio."""
    import numpy as np

    if fixture_path.suffix.lower() == ".pcm":
        out.write_bytes(fixture_path.read_bytes())
        return

    import sphn

    data, _ = sphn.read(str(fixture_path), sample_rate=SAMPLE_RATE_HZ)
    wave = np.asarray(data, dtype="float32")
    if wave.ndim > 1 and wave.shape[0] > 1:
        wave = wave.mean(axis=0, keepdims=True)
    flat = np.clip(wave.reshape(-1), -1.0, 1.0)
    out.write_bytes((flat * 32767.0).astype("<i2").tobytes())


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


@dataclass
class Bundle:
    gen: Any
    audio_tokenizer: Any
    text_tokenizer: Any
    identity: ModelIdentity
    config_raw: dict[str, Any]
    load_s: float
    warmup_s: float


def build(hf_repo: str, *, max_steps: int) -> Bundle:
    """Load the model exactly the way moshi_mlx 0.2.12's own script does.

    Deviating here would mean measuring something upstream does not ship, so
    the sequence below is deliberately unimaginative.
    """
    import mlx.core as mx
    import mlx.nn as nn
    import sentencepiece
    from huggingface_hub import hf_hub_download
    from moshi_mlx import models, utils

    started = time.perf_counter()
    config_path = hf_hub_download(hf_repo, "config.json")
    config_raw: dict[str, Any] = json.loads(Path(config_path).read_text(encoding="utf-8"))

    mimi_weights = hf_hub_download(hf_repo, config_raw["mimi_name"])
    moshi_name = config_raw.get("moshi_name", "model.safetensors")
    moshi_weights = hf_hub_download(hf_repo, moshi_name)
    tokenizer_path = hf_hub_download(hf_repo, config_raw["tokenizer_name"])

    lm_config = models.LmConfig.from_config_dict(config_raw)
    model = models.Lm(lm_config)
    model.set_dtype(mx.bfloat16)
    if moshi_weights.endswith(".q4.safetensors"):
        nn.quantize(model, bits=4, group_size=32)
    elif moshi_weights.endswith(".q8.safetensors"):
        nn.quantize(model, bits=8, group_size=64)

    print("loading weights: " + moshi_weights, file=sys.stderr)
    if hf_repo.endswith("-candle"):
        model.load_pytorch_weights(moshi_weights, lm_config, strict=True)
    else:
        model.load_weights(moshi_weights, strict=True)

    text_tokenizer = sentencepiece.SentencePieceProcessor(tokenizer_path)
    audio_tokenizer = models.mimi.Mimi(models.mimi_202407(32))
    audio_tokenizer.load_pytorch_weights(str(mimi_weights), strict=True)
    load_s = time.perf_counter() - started

    print("warming up", file=sys.stderr)
    warm_started = time.perf_counter()
    model.warmup()
    warmup_s = time.perf_counter() - warm_started

    gen = models.LmGen(
        model=model,
        max_steps=max_steps,
        text_sampler=utils.Sampler(top_k=25, temp=0),
        audio_sampler=utils.Sampler(top_k=250, temp=0.8),
        check=False,
    )

    delay_ms, delay_source = discover_delay_ms(config_raw)
    prefix_ms, prefix_source = discover_silence_prefix_ms(config_raw)
    identity = ModelIdentity(
        hf_repo=hf_repo,
        revision=_revision_from_cache(moshi_weights),
        weights_file=moshi_name,
        weights_blob=_blob_from_cache(moshi_weights),
        weights_bytes=Path(moshi_weights).stat().st_size,
        mimi_file=str(config_raw["mimi_name"]),
        tokenizer_file=str(config_raw["tokenizer_name"]),
        quantization=quantization_from_weights(moshi_name),
        runtime="mlx",
        delay_ms=delay_ms,
        delay_source=delay_source,
        silence_prefix_ms=prefix_ms,
        silence_prefix_source=prefix_source,
    )
    return Bundle(
        gen=gen,
        audio_tokenizer=audio_tokenizer,
        text_tokenizer=text_tokenizer,
        identity=identity,
        config_raw=config_raw,
        load_s=load_s,
        warmup_s=warmup_s,
    )


def _scalar(head: Any) -> float:
    """One probability out of an extra head, whatever shape it arrived in.

    Upstream indexes `[0, 0, 0]`. This tries that first and then degrades,
    because a head arriving with a different rank should cost a slightly odd
    number in the report, not the whole run.
    """
    try:
        return float(head[0, 0, 0].item())
    except Exception:
        pass
    try:
        return float(head.reshape(-1)[0].item())
    except Exception:
        return float(head)


@dataclass
class PassResult:
    tokens: list[TokenEvent]
    vad_samples: list[VadSample]
    step_ms: list[float]
    padding_steps: int
    inference_s: float


def transcribe(bundle: Bundle, fixture: Fixture, *, vad: bool, echo: bool) -> PassResult:
    """Stream the fixture through the model one 80 ms frame at a time.

    Every step is timed individually: a mean speed factor above 1x can still
    hide steps that blow the 80 ms budget, and a stream that stalls
    periodically is a different problem from one that is uniformly slow.
    """
    import mlx.core as mx

    audio = mx.array(fixture.samples)
    tokens: list[TokenEvent] = []
    vad_samples: list[VadSample] = []
    step_ms: list[float] = []
    padding_steps = 0

    started = time.perf_counter()
    for step in range(fixture.frames):
        offset = step * SAMPLES_PER_FRAME
        step_started = time.perf_counter()
        block = audio[:, None, offset : offset + SAMPLES_PER_FRAME]
        codes = bundle.audio_tokenizer.encode_step(block).transpose(0, 2, 1)
        heads: tuple[float, ...] = ()
        if vad:
            text_token, extra = bundle.gen.step_with_extra_heads(codes[0])
            if extra:
                heads = tuple(_scalar(head) for head in extra)
        else:
            text_token = bundle.gen.step(codes[0])
        # `.item()` forces MLX's lazy graph to evaluate, so the step timing
        # below is real work rather than graph construction.
        token_id = int(text_token[0].item())
        step_ms.append((time.perf_counter() - step_started) * 1000)

        if heads:
            vad_samples.append(VadSample(step=step, heads=heads))
        if token_id in PADDING_TOKEN_IDS:
            padding_steps += 1
        else:
            piece = str(bundle.text_tokenizer.id_to_piece(token_id))
            tokens.append(
                TokenEvent(
                    step=step,
                    token_id=token_id,
                    piece=piece,
                    wall_ms=(time.perf_counter() - started) * 1000,
                )
            )
            if echo:
                print(piece.replace("▁", " "), end="", file=sys.stderr, flush=True)
        if step and step % 250 == 0 and not echo:
            print("  step " + str(step) + "/" + str(fixture.frames), file=sys.stderr)

    if echo:
        print("", file=sys.stderr)
    return PassResult(
        tokens=tokens,
        vad_samples=vad_samples,
        step_ms=step_ms,
        padding_steps=padding_steps,
        inference_s=time.perf_counter() - started,
    )


def speed_of(result: PassResult, fixture: Fixture, bundle: Bundle) -> SpeedReport:
    return SpeedReport(
        fixture_ms=fixture.fixture_ms,
        pushed_ms=fixture.pushed_ms,
        steps=fixture.frames,
        load_s=bundle.load_s,
        warmup_s=bundle.warmup_s,
        inference_s=result.inference_s,
        step_ms=result.step_ms,
    )


# --------------------------------------------------------------------------
# Artifacts
# --------------------------------------------------------------------------


def write_artifacts(
    out_dir: Path,
    *,
    findings: Findings,
    main: PassResult,
    vad_result: PassResult | None,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    token_log = out_dir / "b1-tokens.jsonl"
    with token_log.open("w", encoding="utf-8") as handle:
        for token in main.tokens:
            handle.write(
                json.dumps(
                    {
                        "step": token.step,
                        "stream_ms": token.step * FRAME_DURATION_MS,
                        "wall_ms": round(token.wall_ms, 2),
                        "token_id": token.token_id,
                        "piece": token.piece,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    artifacts = {"token log": str(token_log)}

    if vad_result is not None and vad_result.vad_samples:
        vad_csv = out_dir / "b1-vad.csv"
        widest = max(len(s.heads) for s in vad_result.vad_samples)
        header = ["step", "stream_ms"] + ["head_" + str(i) for i in range(widest)]
        rows = [",".join(header)]
        for sample in vad_result.vad_samples:
            values = [format(v, ".6f") for v in sample.heads]
            values += [""] * (widest - len(values))
            rows.append(",".join([str(sample.step), str(sample.step * FRAME_DURATION_MS)] + values))
        vad_csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
        artifacts["vad series"] = str(vad_csv)

    report = out_dir / "b1-report.json"
    report.write_text(
        json.dumps(_report_dict(findings, main), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    artifacts["machine report"] = str(report)

    summary_path = out_dir / "B1-summary.txt"
    artifacts["this summary"] = str(summary_path)
    findings.artifacts = artifacts
    summary_path.write_text(render(findings), encoding="utf-8")
    return artifacts


def _report_dict(findings: Findings, main: PassResult) -> dict[str, Any]:
    identity = findings.identity
    speed = findings.speed
    retraction = findings.retraction
    return {
        "environment": findings.env,
        "fixture": findings.fixture,
        "identity": {
            "hf_repo": identity.hf_repo,
            "revision": identity.revision,
            "weights_file": identity.weights_file,
            "weights_blob": identity.weights_blob,
            "weights_bytes": identity.weights_bytes,
            "quantization": identity.quantization,
            "runtime": identity.runtime,
            "asr_version": identity.asr_version,
            "delay_ms": identity.delay_ms,
            "delay_source": identity.delay_source,
            "silence_prefix_ms": identity.silence_prefix_ms,
            "silence_prefix_source": identity.silence_prefix_source,
        },
        "config": findings.config_text,
        "retraction": {
            "clean": retraction.clean,
            "steps_observed": retraction.steps_observed,
            "tokens_emitted": retraction.tokens_emitted,
            "padding_steps": retraction.padding_steps,
            "prefix_violations": len(retraction.prefix_violations),
            "word_mutations": len(retraction.word_mutations),
        },
        "speed": {
            "fixture_ms": speed.fixture_ms,
            "pushed_ms": speed.pushed_ms,
            "steps": speed.steps,
            "load_s": speed.load_s,
            "warmup_s": speed.warmup_s,
            "inference_s": speed.inference_s,
            "realised_factor": speed.realised_factor,
            "verdict": speed.verdict,
            "step_ms": [round(ms, 3) for ms in main.step_ms],
        },
        "words": [
            {"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms, "pieces": w.pieces}
            for w in findings.words
        ],
        "vad": None
        if findings.vad is None
        else {
            "head_count": findings.vad.head_count,
            "head_index": findings.vad.head_index,
            "samples": findings.vad.samples,
            "stats": findings.vad.stats,
            "crossings": {
                threshold: [
                    {"stream_ms": c.stream_ms, "p": c.probability, "after": c.preceding_word}
                    for c in crossings
                ]
                for threshold, crossings in findings.vad.crossings.items()
            },
        },
    }


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------


def self_check_findings() -> Findings:
    """Render the block from invented numbers, so the plumbing is visible
    before anyone spends twenty minutes downloading weights."""
    tokens = [
        TokenEvent(step=10, token_id=101, piece="▁Bonjour", wall_ms=300.0),
        TokenEvent(step=13, token_id=102, piece="▁tout", wall_ms=390.0),
        TokenEvent(step=15, token_id=103, piece="▁le", wall_ms=450.0),
        TokenEvent(step=17, token_id=104, piece="▁monde", wall_ms=510.0),
    ]
    identity = ModelIdentity(
        hf_repo=DEFAULT_REPO,
        revision="0000000000000000000000000000000000000000",
        weights_file="model.q4.safetensors",
        weights_blob="deadbeef",
        weights_bytes=1_000_000_000,
        mimi_file="mimi.safetensors",
        tokenizer_file="tokenizer.model",
        quantization="q4",
        runtime="mlx",
        delay_ms=500,
        delay_source="SELF-CHECK",
        silence_prefix_ms=0,
        silence_prefix_source="SELF-CHECK",
    )
    words = assemble_words(tokens, delay_ms=500)
    return Findings(
        env=describe_environment(),
        fixture={
            "path": "SELF-CHECK (no audio was read)",
            "fixture_ms": 90_000,
            "pushed_ms": 92_000,
            "frames": 1150,
            "trailing_silence_ms": TRAILING_SILENCE_MS,
            "channels_mixed": False,
        },
        identity=identity,
        speed=SpeedReport(
            fixture_ms=90_000,
            pushed_ms=92_000,
            steps=1150,
            load_s=1.0,
            warmup_s=1.0,
            inference_s=46.0,
            step_ms=[40.0] * 1150,
        ),
        retraction=analyse_retraction(tokens, steps_observed=1150, padding_steps=1146),
        tokens=tokens,
        words=words,
        config_text='{"self_check": true}',
        artifacts={"nothing written": "self-check does not touch the filesystem"},
        vad=None,
        vad_skipped_because="self-check",
        self_check=True,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spike_b1.probe", description="Spike B1 — MLX probe")
    parser.add_argument("audio", nargs="?", help="French fixture: wav/mp3/flac/opus, or raw .pcm")
    parser.add_argument("--hf-repo", default=DEFAULT_REPO)
    parser.add_argument(
        "--vad-repo",
        default=DEFAULT_VAD_REPO,
        help="weights carrying the extra VAD heads; a second pass over the same audio",
    )
    parser.add_argument("--no-vad-pass", action="store_true", help="skip question 4's VAD half")
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parent / "out"))
    parser.add_argument(
        "--silence-prefix-ms",
        type=int,
        default=0,
        help="prepend silence; 0 matches upstream stt_from_file_mlx.py exactly",
    )
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--write-pcm", default=None, help="also save 24 kHz s16le mono for replay")
    parser.add_argument("--quiet", action="store_true", help="do not echo the live transcript")
    parser.add_argument("--self-check", action="store_true", help="render the block, load nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.self_check:
        print(render(self_check_findings()))
        return 0

    if not args.audio:
        print("error: a fixture path is required (or use --self-check)", file=sys.stderr)
        return 2

    audio_path = Path(args.audio).expanduser()
    if not audio_path.is_file():
        print("error: no such fixture: " + str(audio_path), file=sys.stderr)
        return 2

    fixture = load_fixture(
        audio_path,
        silence_prefix_ms=args.silence_prefix_ms,
        trailing_silence_ms=TRAILING_SILENCE_MS,
    )
    print(
        "fixture: "
        + str(fixture.fixture_ms / 1000)
        + " s, "
        + str(fixture.frames)
        + " frames to push",
        file=sys.stderr,
    )
    max_steps = args.max_steps or (fixture.frames + 64)

    bundle = build(args.hf_repo, max_steps=max_steps)
    main_pass = transcribe(bundle, fixture, vad=False, echo=not args.quiet)

    words = assemble_words(
        main_pass.tokens,
        delay_ms=bundle.identity.delay_ms,
        silence_prefix_ms=fixture.silence_prefix_ms,
    )
    retraction = analyse_retraction(
        main_pass.tokens,
        steps_observed=fixture.frames,
        padding_steps=main_pass.padding_steps,
    )

    vad_report: VadReport | None = None
    vad_identity: ModelIdentity | None = None
    vad_speed: SpeedReport | None = None
    vad_result: PassResult | None = None
    skipped = ""
    if args.no_vad_pass:
        skipped = "--no-vad-pass was given"
    else:
        print("\nsecond pass for the VAD heads: " + args.vad_repo, file=sys.stderr)
        vad_bundle = build(args.vad_repo, max_steps=max_steps)
        vad_result = transcribe(vad_bundle, fixture, vad=True, echo=False)
        vad_identity = vad_bundle.identity
        vad_speed = speed_of(vad_result, fixture, vad_bundle)
        vad_report = analyse_vad(
            vad_result.vad_samples,
            head_index=VAD_HEAD_INDEX,
            thresholds=VAD_THRESHOLDS,
            delay_ms=vad_bundle.identity.delay_ms,
            silence_prefix_ms=fixture.silence_prefix_ms,
            words=words,
        )

    findings = Findings(
        env=describe_environment(),
        fixture={
            "path": fixture.path,
            "fixture_ms": fixture.fixture_ms,
            "pushed_ms": fixture.pushed_ms,
            "frames": fixture.frames,
            "trailing_silence_ms": fixture.trailing_silence_ms,
            "channels_mixed": fixture.channels_mixed,
        },
        identity=bundle.identity,
        speed=speed_of(main_pass, fixture, bundle),
        retraction=retraction,
        tokens=main_pass.tokens,
        words=words,
        config_text=json.dumps(bundle.config_raw, ensure_ascii=False, indent=2),
        vad=vad_report,
        vad_identity=vad_identity,
        vad_speed=vad_speed,
        vad_skipped_because=skipped,
    )

    if args.write_pcm:
        write_canonical_pcm(audio_path, Path(args.write_pcm))

    write_artifacts(Path(args.out_dir), findings=findings, main=main_pass, vad_result=vad_result)
    print(render(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
