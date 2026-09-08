# Spike B1 — Kyutai STT on MLX

**Status: written, never executed.** Nothing in this directory has been run
against the model. It cannot be: it needs Apple silicon, and it was built in a
Linux sandbox with no GPU. Everything it *concludes* is unit-tested
(`backend/tests/unit/test_spike_b1_analysis.py`, 37 tests); everything it
*measures* is waiting for you.

Spike B1 is the MLX half of Spike B after ADR-13 split it. It answers four
questions and nothing else:

| # | Question | Decides |
|---|---|---|
| 1 | Does emitted text ever change after it is emitted? | X-14, the append-only invariant, and A-2's open half |
| 2 | Realised speed factor — wall time vs. audio duration | A-12, whether the D-05 flush trick has headroom on MLX |
| 3 | Quantization and model identity | `Meeting.asr_version` (ADR-13 consequence 3), and whether later WER numbers are comparable |
| 4 | Event shape — word text, word timestamps, end-of-turn probability | The tech spec §9.1 mapping and the §9.3 `[measure]` thresholds |

It answers **none** of Spike B2's questions. Concurrent independent streams
(A-3) and GPU capacity (A-4) are properties of `moshi-server` on CUDA and cannot
be observed here.

---

## Before you run it: record a fixture

`backend/tests/fixtures/audio/` is empty apart from a `.gitkeep`, so there is
nothing to reuse. Record this:

**60–90 seconds of French, one speaker, on the microphone you would actually
use in a meeting** — laptop or headset, at a normal desk, room noise included.
Not a studio recording: the point is to see what the model does with the audio
this product will really get.

Fit these into it, because each one answers a different question:

| Put in | Why |
|---|---|
| 4–6 clear end-of-turn pauses, ~1–2 s | Question 4 has nothing to look at otherwise. These are what tune the 0.5 end-of-turn threshold. |
| 2–3 short pauses **under 500 ms** mid-sentence | Shows whether the 700 ms silence threshold splits a phrase that was not finished. This bug (L-13) has already been fixed once. |
| Numbers, a date, a proper noun, an acronym | "vendredi 14", "Sarah", "le devis de 12 400 euros". Meeting notes live or die on these, and they are where WER hurts. |
| Two or three hesitations ("euh", a false start) | Real speech has them; the fake recognizer never did. |

Length matters both ways: under ~30 s the speed factor is dominated by
start-up effects, and over ~2 minutes you will not want to re-record it.

Any format `sphn` reads works — wav, mp3, flac, opus — and it is resampled to
24 kHz internally. Raw `.pcm` is also accepted, in the canonical format from
tech spec §8.1 (24 kHz, signed 16-bit little-endian, mono).

**Also save a verbatim text of what you said**, in the same directory, same
basename, `.txt`. B1 does not use it. Slice 4's WER measurement (A-10) does, and
writing it down while you still remember the false starts costs you two minutes
now instead of a re-record later.

**Do not commit the recording without deciding to.** `backend/tests/fixtures/`
is not gitignored, so a `git add -A` would put your voice in the repository
permanently. That is a Q3 (retention) and A-11 (consent) decision, not a
mechanical one. Keeping it outside the repo and passing an absolute path works
fine.

---

## Run it

One command, from the repository root:

```bash
uv run --script backend/tools/spike_b1/probe.py path/to/your-fixture.wav
```

`--script` builds a throwaway environment from the PEP 723 header in
`probe.py`. It does **not** touch `backend/pyproject.toml`: MLX is macOS/arm64
only, and ADR-13 consequence 5 keeps it out of this project's dependency graph
so a Linux checkout keeps installing.

First run downloads two model repositories (a few GB) into
`~/.cache/huggingface`. Later runs do not.

Then paste the whole `PASTE THIS WHOLE BLOCK BACK VERBATIM` block into
`docs/spikes/B1-findings.md` and send it over. It is plain text, about 120
lines, and it contains every number needed to design the adapter.

### Before you download anything

```bash
uv run --script backend/tools/spike_b1/probe.py --self-check
```

Renders the same report from invented numbers in about a second, so you can see
the output shape and confirm the plumbing works before spending twenty minutes
on weights. Every line of it is stamped `SELF-CHECK — NOT A MEASUREMENT`.

### Flags worth knowing

| Flag | Default | Why you would change it |
|---|---|---|
| `--no-vad-pass` | off | Skips the second pass. Halves the runtime and the download, and leaves question 4's end-of-turn half unanswered. |
| `--write-pcm out.pcm` | off | Also writes the canonical 24 kHz s16le mono, so `tools/replay` can drive the same recording in Slice 4. |
| `--quiet` | off | Stops echoing the transcript as it arrives. |
| `--out-dir` | `backend/tools/spike_b1/out/` | Where the artifacts land. Gitignored, anchored. |
| `--silence-prefix-ms` | `0` | `0` reproduces upstream's `stt_from_file_mlx.py` exactly. The report tells you whether the build's own config asks for a prefix. |

### Why there are two passes

Upstream's `--vad` flag switches the default repository to
`kyutai/stt-1b-en_fr-candle`, because the `-mlx` weights do not carry the extra
VAD heads. So question 4's end-of-turn half needs a second pass over the same
audio against different weights, and those are usually a different quantization
too. The report keeps the two sets of numbers apart and labels both; do not
merge them, and do not read the second pass's speed factor as the answer to
question 2.

---

## What is in here

| File | Runs where | Tested |
|---|---|---|
| `probe.py` | Apple silicon only — drives the model, records what it did | no (it cannot run in CI or in a sandbox) |
| `b1_analysis.py` | anywhere — turns a token log into the four answers | yes, 37 tests |
| `b1_summary.py` | anywhere — renders the pasteable block | yes, same file |

The split is the point. `probe.py` measures and concludes nothing; the two pure
modules conclude and measure nothing. That is what lets the reasoning be tested
on a machine that cannot load the model.

The retraction detector is the clearest case. Question 1's expected answer is
"no retraction", which makes a broken detector and a correct one produce the
same output — so the tests feed it a synthetic retraction and require it to
fire. A clean result then means it looked and saw nothing, rather than that it
cannot see.

## What it deliberately does not do

* **It does not touch `speech/adapters/kyutai/`.** The adapter is Slice 4, and
  writing it before these four answers arrive is how a `[measure]` guess becomes
  a permanent value.
* **It does not measure WER.** That needs a reference transcript and is A-10,
  in Slice 4.
* **It does not check run-to-run determinism.** The text sampler is greedy but
  the audio sampler is not, so a second run may differ. If a number decides
  something, run it twice.
