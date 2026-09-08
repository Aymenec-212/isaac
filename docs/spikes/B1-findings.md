# Spike B1 — Kyutai STT on MLX: findings

> **STATUS: RUN.** Filled in from the artifacts committed at
> `docs/mosaique-b1-main/` (`B1-summary.txt`, `b1-report.json`,
> `b1-tokens.jsonl`). Every number below is copied from those files; nothing
> here is estimated. Where the probe did not measure something, the row says
> NOT MEASURED rather than carrying a guess.

**Spike:** B1 (MLX half of Spike B, after ADR-13 amendment M-4)
**Run by:** Aymen
**Run on:** 2026-09-08 (probe timestamp `2026-09-08T12:25:26Z`)
**Machine:** Apple M1, 9 GB, macOS 14.3, Python 3.12.9,
`moshi_mlx 0.2.12` / `mlx 0.26.5`
**Blocks:** Slice 4 — **now unblocked**
**Answers:** A-2 (open half), A-12, and the §9.1/§9.3 mapping. **Not** A-3, A-4
or A-10.

---

## 0. Fixture

| Field | Value |
|---|---|
| File | `/tmp/mosaique-probe-test.wav` — **not committed**; kept off the repository as a Q3/A-11 decision |
| Duration | 64.07 s (825 frames of 80 ms); 66.00 s pushed with upstream's 2 s trailing silence |
| Speaker(s) | one, French, first person ("je m'appelle Ayman", Casablanca) |
| Microphone | not recorded by the probe |
| Room | not recorded by the probe |
| Reference transcript saved? | **no** — which is why A-10 (WER) is still open |
| Contents | 92 words, 4 sentences. Three mid-transcript sentence ends, one 24 s silence, and mid-phrase pauses up to 1120 ms |

**Caveat the runner reported:** the machine was under memory pressure during the
run (Chrome and Docker open, 9 GB total). That affects §2 and only §2 — wall
time. It does not touch §1, §3 or §4, and it does not touch the word timings the
§9.3 retune is built on, because those are derived from frame counts, not from a
clock (ADR-11). This is the first time that design property has paid for itself
outside a replay.

---

## 1. Retraction — does emitted text ever change after it is emitted?

| Field | Value |
|---|---|
| Verdict | **NO RETRACTION OBSERVED** |
| Steps observed | 825 |
| Text tokens emitted | 162 |
| Padding steps | 663 |
| Prefix violations | 0 |
| Settled-word mutations | 0 |

**What this changed:** X-14 stands **for the MLX runtime**. `revision` remains a
monotone counter, the client reconciler is unchanged, and the segmenter grew no
correction path.

Read the observation level with it. `moshi_mlx`'s `LmGen` returns at most one
text token per 80 ms step and exposes no revision channel, so on this runtime
append-only is a property of the API rather than a measurement of the model. The
detector is unit-tested against a synthetic retraction, so the result means it
looked and saw nothing — but it does not transfer to `moshi-server`, whose wire
protocol can revise, and that stays Spike B2's question.

---

## 2. Realised speed factor

| Field | Value |
|---|---|
| Realised factor | **1.24x** |
| Verdict | **MARGINAL** |
| Audio pushed | 66.00 s |
| Inference wall time | 53.22 s |
| Per-step p50 / p95 / max | 59.4 / 75.2 / 1468.4 ms (budget 80 ms) |
| Steps over budget | 23 of 825 (2.8%) |
| Model load / warmup | 284.26 s / 3.69 s (excluded) |

**What this changed: A-12 is answered NEGATIVELY for MLX.** The D-05 flush trick
assumes the runtime can process several times faster than real time and catch
up on demand. At 1.24x there is nothing to catch up with, so
`MlxBackend.flush()` pushes the delay's worth of silence and waits, and
segment-close latency on MLX reverts to roughly the 500 ms model delay. Recorded
in code on `MlxBackend.flush`, not only here.

Two readings of the distribution worth keeping:

* **The two worst steps are the first two** (1468 ms and 684 ms) — first-call
  graph compilation, not a mid-stream stall. Excluding them the factor is
  1.291x, still MARGINAL, so the verdict does not depend on the reading.
* **The over-budget steps cluster** (indices 675–712, and 768). That is a real
  sustained slow patch of about three seconds of stream, consistent with the
  memory pressure reported above. At 1.24x a backlog drains at only 0.24 s per
  second, so a 1.4 s stall takes about six seconds to work off — which the
  §8.4 bounded queue will see as `delayed`.

**Not re-run.** The runner chose to accept one sample rather than repeat it; a
larger run is deferred until after Slice 4. The headline verdict is robust to
that, since 1.24x is far from the 1.5x boundary.

---

## 3. Quantization and model identity

| Field | Value |
|---|---|
| `Meeting.asr_version` | **`kyutai/stt-1b-en_fr@mlx-bf16`** |
| HF repo | `kyutai/stt-1b-en_fr-mlx` |
| Revision | `2b995724eef1e964b7ccb6a762b35a665c4abe0d` |
| Weights file | `model.safetensors` (1.98 GB) |
| Quantization | **bf16** — *not* the `q4` ADR-13 used as its example |
| Model delay | **500 ms, read from the build** (`config.stt_config.audio_delay_seconds = 0.5`) |
| Silence prefix the config asks for | **0 ms** (`audio_silence_prefix_seconds = 0.0`) |
| VAD pass repo / quantization | NOT MEASURED — the pass was skipped |

**What this changed:**

* The ADR's example string was a guess and is now a measurement.
  `identity.quantization_from_weights` reads it from the filename the way the
  loader does, so a later `q4` build relabels itself without a code change.
* The delay is **read, not assumed**. `PieceAssembler` and
  `transcribed_offset_ms` use the build's own 500 ms.
* The config asks for **no** silence prefix, so the adapter applies none and
  timestamps need no shift.
* A-16 (MLX and CUDA agree within a tolerance) stays UNVALIDATED. A bf16 MLX
  number is still not a bf16 CUDA number: same precision, different runtime.

---

## 4. Event shape

| Field | Value |
|---|---|
| Word text | sentencepiece pieces, U+2581 marks a word start; 162 pieces → 92 words, 39 of them multi-piece |
| Word-level timestamps | **derived, not emitted** — step index × 80 ms, minus the 500 ms delay |
| `end_ms` | **inferred** (last piece's step + 1); the runtime emits none |
| Per-word confidence | **not emitted** — `WordEvent.confidence` stays `None` |
| End-of-turn signal | **NOT MEASURED** — `--no-vad-pass` was given, and the `-mlx` weights carry no VAD heads regardless |
| Probability attached | NOT MEASURED |
| Crossings at 0.3 / 0.5 / 0.7 / 0.9 | NOT MEASURED |

**What this changed, and it is the largest consequence of the whole spike:**

**On MLX there is no end-of-turn event at all.** §9.3's primary closing rule is
absent on the runtime this project develops against, so segment boundaries fall
to the silence timer alone — and the word timings show the silence timer cannot
carry them:

| Gap | Between | Real boundary? |
|---|---|---|
| 1680 ms | `formation.` → `Ce` | yes |
| 1120 ms | `endroits` → `familiers` | **no — inside a noun phrase** |
| 1120 ms | `Alors` → `bonjour,` | no |
| 960 ms | `toi` → `et` | no |
| 880 ms | `à` → `Casablanca,` | **no — inside a prepositional phrase** |
| 880 ms | `caractère.` → `J'ai` | yes |
| 720 ms | `crée` → `un` | **no** |

The largest mid-phrase gap (1120 ms) is **longer** than the smallest real
sentence break (880 ms). The distributions overlap, so **no silence threshold
separates them**. The old 700 ms default splits a phrase six times in 64 s.

Punctuation does separate them: all three mid-transcript `.` marks land on real
boundaries, none inside a phrase, and commas — checked separately — are followed
by gaps of 0–640 ms, squarely mid-phrase.

So §9.3 gained a rule and one threshold moved:

| §9.3 value | Was | Now | Basis |
|---|---|---|---|
| silence | 700 ms | **1200 ms** | clears the observed 1120 ms mid-phrase maximum |
| sentence-final punctuation | — | **new closing rule** | 3/3 boundaries, 0 false positives |
| end-of-turn threshold | 0.5 | **0.5, untouched** | unmeasurable on a runtime that emits no such event |
| max segment | 15 s | **15 s, untouched** | never fired; longest natural segment 12.7 s |

`tests/unit/test_segmentation_against_real_audio.py` replays these word timings
through the real segmenter and asserts the four sentences come out whole, so the
tuning is a passing test rather than a paragraph.

---

## 5. Raw output

The probe's own block is committed verbatim at
`docs/mosaique-b1-main/B1-summary.txt`, alongside `b1-report.json` (every
per-step timing and word) and `b1-tokens.jsonl` (every token with its
timestamp). They are the evidence for everything above and are not reproduced
here.

---

## 6. What this spike did not answer

| Question | Why not | Where it goes |
|---|---|---|
| A-3 — concurrent independent streams | a property of a serving runtime, not the model | Spike B2, needs CUDA |
| A-4 — GPU capacity | same | Spike B2 / Spike C |
| A-10 — French WER | no reference transcript was saved, and one 64 s fixture is not a WER sample | Slice 4 smoke test, then Slice 6 |
| A-16 — do MLX and CUDA agree? | only one runtime has run | when a CUDA machine exists |
| The end-of-turn threshold | the VAD pass was skipped; the `-mlx` weights carry no heads | Spike B2, on `moshi-server`'s `Step` messages |
| Run-to-run determinism | not checked; the audio sampler is not greedy | if a number ever decides something |
| Cross-talk (A-1) | a different spike | Spike A |

---

## 7. Decision

**Slice 4 started as planned, with one change to §9.3 and one expectation
withdrawn.** The change: segment closing now takes sentence-final punctuation as
a first-class rule, because the runtime emits no end-of-turn signal and silence
alone provably cannot do the job for the speaker measured. The withdrawal: A-12
is negative on MLX, so the D-05 flush trick is not available there and
final-segment latency on the development runtime is bounded below by the model
delay rather than by 125 ms.

Nothing about the audio format changed. §8.1's 24 kHz / 80 ms / 1920 samples is
exactly what Mimi's `encode_step` consumes, and the build asks for no silence
prefix, so the worklet, the frame codec and the gateway are untouched.

**PROJECT_STATE.md rows updated from this file:** A-2, A-12, the `asr_version`
row in §8, the §9.3 threshold rows in §8, and §9's Spike B1 row — with this
file named as the evidence and 2026-09-08 as the date.
