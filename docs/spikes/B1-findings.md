# Spike B1 — Kyutai STT on MLX: findings

> **STATUS: TEMPLATE. NOT RUN. NOTHING BELOW IS EVIDENCE.**
>
> Every field is a placeholder until someone runs
> `backend/tools/spike_b1/probe.py` on Apple silicon and fills it in. Until
> then this document proves nothing, and `PROJECT_STATE.md` must not cite it.
> Delete this block when the numbers are real.

**Spike:** B1 (MLX half of Spike B, after ADR-13 amendment M-4)
**Run by:** _(name)_
**Run on:** _(date)_
**Machine:** _(chip, memory, macOS version)_
**Blocks:** Slice 4
**Answers:** A-2 (open half), A-12, and the §9.1/§9.3 mapping. **Not** A-3, A-4
or A-10.

---

## 0. Fixture

| Field | Value |
|---|---|
| File | _(path — say whether it is committed)_ |
| Duration | _(s)_ |
| Speaker(s) | _(one voice? accent? region?)_ |
| Microphone | _(laptop / headset / which)_ |
| Room | _(quiet office / open plan / café)_ |
| Reference transcript saved? | _(yes/no — Slice 4 needs it for WER)_ |
| Contents | _(how many end-of-turn pauses, any sub-500 ms pauses, numbers/dates/proper nouns, hesitations)_ |

If the fixture is not representative of a real meeting, say so here rather than
letting the numbers below inherit the flattery.

---

## 1. Retraction — does emitted text ever change after it is emitted?

**Decides:** X-14 (the append-only invariant), the second half of A-2, the
segmenter's `revision` semantics, and the client reconciler's revision rules.

| Field | Value |
|---|---|
| Verdict | _(NO RETRACTION OBSERVED / RETRACTION OBSERVED)_ |
| Steps observed | _( )_ |
| Text tokens emitted | _( )_ |
| Prefix violations | _( )_ |
| Settled-word mutations | _( )_ |

**What this changes:**

- [ ] No retraction → X-14 stands **for the MLX runtime**. `revision` stays a
      monotone counter, the reconciler is unchanged, and the segmenter needs no
      correction path. Record that this is an API-shape result, not a model
      measurement — `moshi-server`'s wire protocol is still unproven (B2).
- [ ] Retraction observed → X-14 is **withdrawn**. The segmenter (§9.3) and the
      client reconciler (§7.3) both grow a correction path, `revision` becomes
      a correction mechanism rather than a counter, and the implementation plan
      gains work between Slices 3 and 4. Write down exactly what changed and
      when.

_Notes:_

---

## 2. Realised speed factor

**Decides:** A-12, and therefore whether the D-05 flush trick survives on MLX.

| Field | Value |
|---|---|
| Realised factor | _( x)_ |
| Verdict | _(HEADROOM / MARGINAL / TOO SLOW)_ |
| Audio pushed | _(s)_ |
| Inference wall time | _(s)_ |
| Per-step p50 / p95 / max | _( / / ms — budget 80 ms)_ |
| Steps over budget | _( of )_ |
| Model load / warmup | _(s / s — excluded)_ |

**What this changes:**

- [ ] ≥ 1.5x → `flush()` can be implemented as accelerated catch-up on MLX, as
      `FakeASRSession.flush()` already imitates. A-12 is answered positively
      **for this runtime only**.
- [ ] 1.0–1.5x → A-12 is answered **negatively for MLX**. `flush()` degrades to
      pushing silence and waiting out the model delay, so final-segment latency
      on MLX is ~500 ms worse than the fake predicts. Slice 4's latency budget
      is written against that, and the ledger records it as an MLX number.
- [ ] < 1.0x → Slice 4 is blocked on hardware, not on code. Say so loudly; do
      not tune thresholds against a runtime that cannot keep up.

Watch the p95 as well as the mean. A mean above 1x with a p95 step over 80 ms is
a runtime that stalls periodically, which the bounded queue (§8.4) will see as
overload and turn into `gap` segments.

_Notes:_

---

## 3. Quantization and model identity

**Decides:** the `Meeting.asr_version` string (ADR-13 consequence 3), and
whether any WER number measured later is comparable to any other.

| Field | Value |
|---|---|
| `Meeting.asr_version` | _(e.g. `kyutai/stt-1b-en_fr@mlx-q4`)_ |
| HF repo | _( )_ |
| Revision (commit sha) | _( )_ |
| Weights file | _( )_ |
| Quantization | _(q4 / q8 / bf16)_ |
| Model delay | _( ms — and whether it was read from config or assumed)_ |
| Silence prefix the config asks for | _( ms)_ |
| VAD pass repo / quantization | _( )_ |

**What this changes:**

- The exact string above goes into `Meeting.asr_version` when the adapter is
  written. Without it, MLX-era and CUDA-era transcripts are indistinguishable
  after the fact and every WER comparison built on them is unsound.
- If the model delay came from `config.json` rather than the model card, the
  `transcribed_offset_ms` contract in `speech/interfaces/asr.py` can use a real
  number instead of ~500 ms.
- If the config asks for a silence prefix that the probe did not apply, the
  adapter has to apply it, and every timestamp shifts by that much.
- A-14 (MLX and CUDA agree within a stated tolerance) stays UNVALIDATED
  regardless. It closes when the same fixture has run on both.

_Notes:_

---

## 4. Event shape

**Decides:** the tech spec §9.1 mapping the adapter has to implement, and which
§9.3 thresholds are tunable at all.

| Field | Value |
|---|---|
| Word text | _(how it arrives — pieces? whole words?)_ |
| Words in the fixture | _( )_ |
| Word-level timestamps | _(emitted / derived; resolution)_ |
| `end_ms` | _(emitted / inferred)_ |
| Per-word confidence | _(emitted / not)_ |
| End-of-turn signal | _(yes/no; how many heads)_ |
| Probability attached | _(yes/no)_ |
| Crossings at 0.3 / 0.5 / 0.7 / 0.9 | _( / / / )_ |
| Do the crossings land at real turn boundaries? | _(judgement — look at the words they followed)_ |

**What this changes:**

- `WordEvent(text, start_ms, end_ms, confidence)` — every field the runtime does
  not emit has to be synthesised by the adapter or left `None`. Say which.
- `EndOfTurnEvent(at_ms, probability)` — if no probability arrives, the §9.3
  `end_of_turn_threshold` is not a `[measure]` value, it is dead code, and
  segment closing falls back to the silence timer alone.
- The number of crossings against the transcript is the first real evidence for
  the 0.5 threshold. If 0.5 fires mid-sentence, or misses obvious turn ends,
  record the value that would have worked — that is the number Slice 4 uses.
- Timestamp resolution bounds how precisely `start_ms` can be reported, which
  bounds FR-11 timestamp navigation.

_Notes:_

---

## 5. Raw output

Paste the block the script printed, verbatim, between the fences. Do not tidy
it: the numbers and their caveats belong together.

```text
(paste here)
```

---

## 6. What this spike did not answer

Named so nobody later mistakes silence for a result.

| Question | Why not | Where it goes |
|---|---|---|
| A-3 — does `moshi-server` serve concurrent independent streams cleanly? | Property of a serving runtime, not of the model | Spike B2, needs CUDA |
| A-4 — does one GPU sustain four real-time streams? | Same | Spike B2 / Spike C |
| A-10 — French WER on real meeting audio | Needs a reference transcript and more than one fixture | Slice 4 |
| A-14 — do MLX and CUDA agree? | Only one runtime has been run | When a CUDA machine exists |
| Run-to-run determinism | Not measured; the audio sampler is not greedy | Re-run the fixture if a number matters |
| Cross-talk (A-1) | Different spike entirely | Spike A |

---

## 7. Decision

_One paragraph: does Slice 4 start as planned, start with changes, or not
start? Name the changes._

**Slice 4 shape after B1:** _( )_

**PROJECT_STATE.md rows to update once this is filled in:** A-2, A-12, the
`asr_version` note, and §9's Spike B1 row — with this file named as the
evidence, and the date it was run.
