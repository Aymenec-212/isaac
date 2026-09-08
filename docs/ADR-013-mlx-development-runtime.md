# ADR-13 — MLX as the development ASR runtime

**Date:** 2026-09-07
**Status:** Accepted. Amends ADR-03, ADR-09, tech spec §9.2, Spike B, and the Slice 4 / Slice 6 gates.
**Supersedes nothing.** ADR-03's model choice is unchanged.

---

## Context

ADR-03 chose Kyutai STT-1B en/fr behind `StreamingRecognizer`, served by `moshi-server`
as a separate `asr-runtime` process. `moshi-server` is installed with
`cargo install --features cuda moshi-server` — CUDA is the build feature, not an
optional accelerator. No CUDA GPU is available, and Claude Code's sandbox has no
GPU of any kind.

Kyutai publish `kyutai/stt-1b-en_fr-mlx` and recommend MLX for on-device
inference on Apple silicon. It is the same model, the same weights lineage, the
same 12.5 Hz frame rate and 0.5 s delay.

## Decision

**The model is fixed; the runtime is a configuration choice.**

| Runtime | Where | Purpose |
|---|---|---|
| `fake` | anywhere | Slices 1–3, all CI, all tests that are not about the model |
| `mlx` | Apple silicon, native host process | **Development and the Slice 4 smoke test** |
| `moshi_server` | CUDA host, container | Deployment, and the only runtime that can answer A-3 / A-4 |

Selected by typed config (`MOSAIQUE_ASR_RUNTIME`), fail-fast on an unknown or
unavailable value. Both real backends live inside `speech/adapters/kyutai/`,
because they are one model with two runtimes, and the module boundary is
already where the architecture test enforces it.

## Why this does not change the architecture

Tech spec §9.2 already provides for exactly this: *"If `moshi-server` turns out
not to support concurrent independent streams cleanly, fall back to an
in-process PyTorch adapter inside a dedicated `asr-runtime` service that exposes
the same protocol. Either way, the app-server is unchanged."* MLX is a third
entry in that same slot. Nothing upstream of `StreamingRecognizer` learns which
runtime is in use.

If adopting MLX required a change to the runtime, the segmenter, the ingress, or
the persistence layer, that would be evidence the seam had failed. It does not.

## What MLX does and does not buy

**Answers, because they are properties of the model:**
- A-2, the open half — whether emitted text is ever retracted. If it is, X-14's
  append-only invariant is withdrawn and the reconciler grows.
- A-10 — French WER on real meeting audio, subject to the quantization caveat below.
- Segmentation threshold tuning against real French speech (Slice 4's real work).

**Does not answer, because they are properties of a serving runtime:**
- A-3 — whether `moshi-server` serves concurrent independent streams cleanly.
  Kyutai report 64 simultaneous connections at 3x real time on an L40S; that is
  a vendor figure on hardware we do not have.
- A-4 — whether one GPU sustains four concurrent real-time streams.
- A-12 — the D-05 flush trick. It depends on processing faster than real time
  (~4x on the Rust server). MLX on a laptop may not have that headroom, in which
  case final-segment latency reverts to the model delay **on MLX only**.

**Consequence: Slice 6 is now BLOCKED on access to a CUDA machine.** Slice 4 is
unblocked. This is the trade being made, and it is worth making — it buys three
slices of progress for one deferred dependency.

## Consequences to record

1. **Docker cannot reach Metal on macOS.** The MLX runtime runs as a native host
   process, so the local development topology is three containers plus one host
   process, not four containers. ADR-09's separable-runtimes reasoning is
   unaffected; only the local packaging changes. Deployment topology is unchanged.

2. **Quantization makes MLX WER a different number, not the same number.** If the
   MLX build is quantized, a WER measured there is not the bf16 CUDA WER. Record
   the quantization in the measurement or the number is not comparable.

3. **`Meeting.asr_version` must encode runtime and quantization**, not just the
   model — for example `kyutai/stt-1b-en_fr@mlx-q4` versus
   `kyutai/stt-1b-en_fr@moshi-server-bf16`. The column already exists (spec §37).
   Without this, MLX-era and CUDA-era transcripts become indistinguishable after
   the fact, and every WER comparison built on them is unsound.

4. **`test_architecture.py` must ban the new runtime's imports.** Add `mlx`,
   `moshi_mlx`, and `mlx_lm` to `MODEL_MODULES` if absent. A second backend is
   precisely when a model-boundary test stops being theatre and starts earning
   its keep; leaving it blind to MLX would retire the guarantee at the moment it
   first matters.

5. **MLX dependencies must be platform-gated.** They are macOS/arm64 only, so
   they belong in an optional extra with an environment marker
   (`sys_platform == "darwin" and platform_machine == "arm64"`). A plain
   dependency breaks installation in the Linux sandbox and in any future CI.

## Amendments

| # | Document | Change |
|---|---|---|
| M-1 | Tech spec §9.2 | Three named runtimes behind one adapter, selected by config. `moshi-server` remains the deployment runtime. |
| M-2 | ADR-03 | Model unchanged. Runtime becomes a configuration axis. Revisit trigger unchanged. |
| M-3 | ADR-09 | Local development on macOS is three containers plus a native MLX process. Deployment unchanged. |
| M-4 | Spike B | Splits. **B1 (MLX):** retraction (A-2), French WER (A-10), flush headroom (A-12). Runnable now, blocks Slice 4. **B2 (moshi-server):** concurrent independent streams (A-3), GPU capacity (A-4). Needs CUDA, blocks Slice 6. |
| M-5 | Slice 4 exit gate | Single-stream smoke test against MLX satisfies it. Latency and WER recorded with runtime and quantization named. |
| M-6 | Slice 6 | Add: **BLOCKED on a CUDA host and on Spike B2.** |
| M-7 | Assumptions | Add **A-14**: MLX and CUDA runtimes produce equivalent transcripts within a stated tolerance. Unvalidated until both have run the same fixture. Every number measured on MLX inherits this caveat. |
| M-8 | Q2 | **Partially closed.** EU data residency: not required for now. Inference location for development: MLX on Apple silicon. Production inference host: still open, folded into Slice 6's blocker. Revisit trigger: the first real customer conversation, which also triggers A-11 (legal) and ADR-12 §5. |

## Revisit trigger

A CUDA machine becomes available, or Slice 6 is reached — whichever comes first.
At that point run Spike B2, measure the same fixture on both runtimes, and
resolve A-14 with a number.
