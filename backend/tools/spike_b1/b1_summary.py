"""The pasteable plain-text answer to Spike B1's four questions.

Pure, like `b1_analysis.py`, and for the same reason: the shape of this block is
the deliverable, so it is unit-tested rather than eyeballed once on a Mac.

House rules for what goes in here:

* four numbered sections, one per question in the brief, and nothing else that
  presents itself as an answer;
* every number carries the runtime and quantization it was measured on, because
  ADR-13 consequence 2 says an MLX number and a CUDA number are different
  numbers;
* anything the script assumed rather than read is labelled ASSUMED on the line
  that reports it, not in a footnote at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from b1_analysis import (
    FRAME_DURATION_MS,
    VERDICT_MEANING,
    ModelIdentity,
    RetractionReport,
    SpeedReport,
    TokenEvent,
    VadReport,
    Word,
    percentile,
)

RULE = "=" * 78
THIN = "-" * 78

SELF_CHECK_BANNER = (
    "!!  SELF-CHECK OUTPUT — SYNTHETIC NUMBERS, NOT A MEASUREMENT  !!\n"
    "!!  No model was loaded and no audio was transcribed. Do not paste this\n"
    "!!  block into B1-findings.md; no number below is evidence of anything."
)


@dataclass
class Findings:
    env: dict[str, str]
    fixture: dict[str, Any]
    identity: ModelIdentity
    speed: SpeedReport
    retraction: RetractionReport
    tokens: list[TokenEvent]
    words: list[Word]
    config_text: str
    artifacts: dict[str, str] = field(default_factory=dict)
    vad: VadReport | None = None
    vad_identity: ModelIdentity | None = None
    vad_speed: SpeedReport | None = None
    vad_skipped_because: str = ""
    self_check: bool = False


def _row(label: str, value: object) -> str:
    return "  " + label.ljust(24) + str(value)


def _s(ms: float) -> str:
    return format(ms / 1000, ".2f") + " s"


def render(f: Findings) -> str:
    head = "MOSAIQUE — SPIKE B1 (MLX) — PASTE THIS WHOLE BLOCK BACK VERBATIM"
    out: list[str] = [RULE, head, RULE]
    if f.self_check:
        out.append(SELF_CHECK_BANNER)
    out += _header(f)
    out += _retraction(f)
    out += _speed(f)
    out += _identity(f)
    out += _event_shape(f)
    out += _footer(f)
    if f.self_check:
        out.append(SELF_CHECK_BANNER)
    out.append(RULE)
    return "\n".join(out) + "\n"


def _header(f: Findings) -> list[str]:
    lines = [""]
    for key, value in f.env.items():
        lines.append(_row(key, value))
    fixture_ms = f.fixture["fixture_ms"]
    pushed_ms = f.fixture["pushed_ms"]
    trailing_ms = f.fixture["trailing_silence_ms"]
    frames = f.fixture["frames"]
    lines.append("")
    lines.append(_row("fixture", f.fixture["path"]))
    lines.append(_row("  duration", _s(fixture_ms) + "  (" + str(frames) + " frames of 80 ms)"))
    lines.append(
        _row(
            "  pushed to model",
            _s(pushed_ms) + "  (+" + _s(trailing_ms) + " trailing silence, upstream behaviour)",
        )
    )
    lines.append(_row("  channels mixed", "yes" if f.fixture.get("channels_mixed") else "no"))
    return lines


def _retraction(f: Findings) -> list[str]:
    r = f.retraction
    lines = [
        "",
        THIN,
        "1. RETRACTION — does emitted text ever change after it is emitted?   [X-14]",
        THIN,
        _row("VERDICT", "NO RETRACTION OBSERVED" if r.clean else "RETRACTION OBSERVED"),
        _row("steps observed", r.steps_observed),
        _row("text tokens emitted", r.tokens_emitted),
        _row("padding steps", r.padding_steps),
        _row("prefix violations", len(r.prefix_violations)),
        _row("settled-word mutations", len(r.word_mutations)),
    ]
    for violation in r.prefix_violations[:5]:
        where = "#" + str(violation.index) + ": ..." + violation.before
        lines.append(_row("  prefix break", where))
        lines.append(_row("    became", "..." + violation.after))
    for mutation in r.word_mutations[:5]:
        detail = (
            "snapshot #"
            + str(mutation.index)
            + " position "
            + str(mutation.position)
            + ": "
            + mutation.before
            + " -> "
            + mutation.after
        )
        lines.append(_row("  word changed", detail))
    lines += [
        "",
        "  OBSERVATION LEVEL — read this before believing the verdict.",
        "  moshi_mlx's LmGen returns at most one text token per 80 ms step and",
        "  exposes no revision or correction channel. On this runtime the",
        "  transcript is therefore append-only BY CONSTRUCTION, so a clean",
        "  verdict confirms the shape of the API rather than measuring the model.",
        "  It is still worth having: this is the same detector that will run",
        "  against moshi-server in Spike B2, where a wire protocol CAN retract,",
        "  and it is unit-tested against a synthetic retraction in",
        "  tests/unit/test_spike_b1_analysis.py — so a clean result means the",
        "  detector looked and saw nothing, not that it cannot see.",
    ]
    return lines


def _speed(f: Findings) -> list[str]:
    s = f.speed
    step_line = (
        "p50 "
        + format(percentile(s.step_ms, 50), ".1f")
        + "  p95 "
        + format(percentile(s.step_ms, 95), ".1f")
        + "  max "
        + format(percentile(s.step_ms, 100), ".1f")
        + "   (budget "
        + str(FRAME_DURATION_MS)
        + ".0 ms/step)"
    )
    return [
        "",
        THIN,
        "2. REALISED SPEED FACTOR — wall time vs. audio duration   [A-12, D-05]",
        THIN,
        _row("measured on", f.identity.hf_repo + " (" + f.identity.quantization + ", mlx)"),
        _row("audio pushed", _s(s.pushed_ms)),
        _row("inference wall time", format(s.inference_s, ".2f") + " s"),
        _row("REALISED FACTOR", format(s.realised_factor, ".2f") + "x"),
        _row("VERDICT", s.verdict),
        _row("", VERDICT_MEANING[s.verdict]),
        "",
        _row("fixture-only factor", format(s.fixture_factor, ".2f") + "x  (no trailing silence)"),
        _row("model load", format(s.load_s, ".2f") + " s  (excluded from the factor)"),
        _row("warmup", format(s.warmup_s, ".2f") + " s  (excluded from the factor)"),
        _row("per-step ms", step_line),
        _row("steps over budget", str(s.steps_over_budget) + " of " + str(s.steps)),
        "",
        "  The threshold is 1.5x. Below it, flush() cannot catch up faster than",
        "  the audio arrives, so segment-close latency reverts to the model delay",
        "  and D-05's ~125 ms becomes ~500 ms — on MLX only. This says nothing",
        "  about moshi-server on CUDA, which is Spike B2.",
    ]


def _identity(f: Findings) -> list[str]:
    i = f.identity
    lines = [
        "",
        THIN,
        "3. QUANTIZATION AND MODEL IDENTITY   [Meeting.asr_version, A-10, A-14]",
        THIN,
        _row("Meeting.asr_version", i.asr_version),
        "",
        _row("hf repo", i.hf_repo),
        _row("revision", i.revision),
        _row("weights file", i.weights_file),
        _row("weights blob", i.weights_blob),
        _row("weights size", format(i.weights_bytes / 1e9, ".2f") + " GB"),
        _row("quantization", i.quantization + "  (inferred from the weights filename)"),
        _row("mimi weights", i.mimi_file),
        _row("text tokenizer", i.tokenizer_file),
        _row("model delay", str(i.delay_ms) + " ms  [" + i.delay_source + "]"),
        _row("silence prefix", str(i.silence_prefix_ms) + " ms  [" + i.silence_prefix_source + "]"),
    ]
    if f.vad_identity is not None:
        v = f.vad_identity
        lines += [
            "",
            "  second pass, VAD only — different weights, do NOT mix these numbers:",
            _row("  hf repo", v.hf_repo),
            _row("  revision", v.revision),
            _row("  quantization", v.quantization),
            _row("  asr_version", v.asr_version),
        ]
        if f.vad_speed is not None:
            factor = format(f.vad_speed.realised_factor, ".2f") + "x  (" + v.quantization + ")"
            lines.append(_row("  realised factor", factor))
    lines += [
        "",
        "  Every WER number measured on this build inherits ADR-13 consequence 2:",
        "  a quantized MLX WER is not the bf16 CUDA WER, and A-14 (the two",
        "  runtimes agree within a stated tolerance) stays UNVALIDATED until the",
        "  same fixture has run on both.",
        "",
        "  config.json, as the build reports it:",
        "",
    ]
    lines += ["    " + line for line in f.config_text.splitlines()]
    return lines


def _event_shape(f: Findings) -> list[str]:
    i = f.identity
    words = len(f.words)
    multi = sum(1 for w in f.words if w.pieces > 1)
    lines = [
        "",
        THIN,
        "4. EVENT SHAPE — what the segmenter has to work with   [spec 9.1, 9.3]",
        THIN,
        _row(
            "word text",
            "YES — " + str(len(f.tokens)) + " sentencepiece pieces -> " + str(words) + " words",
        ),
        _row("  multi-piece words", str(multi) + " of " + str(words)),
        _row("word timestamps", "DERIVED, NOT EMITTED — one token per 80 ms step; a word"),
        _row("", "starts at the step of its first piece, minus the"),
        _row("", str(i.delay_ms) + " ms model delay."),
        _row("  resolution", str(FRAME_DURATION_MS) + " ms"),
        _row("  end_ms", "inferred (last piece's step + 1); the runtime emits none"),
        _row("  confidence", "NOT EMITTED — WordEvent.confidence must stay None"),
    ]
    if f.words:
        lines.append("")
        lines.append("  first words, as the adapter would build them:")
        for word in f.words[:8]:
            span = "[" + str(word.start_ms).rjust(6) + " - " + str(word.end_ms).rjust(6) + " ms]  "
            lines.append(_row("", span + word.text))
    lines.append("")
    if f.vad is None:
        lines.append(_row("end-of-turn signal", "NOT MEASURED — " + f.vad_skipped_because))
        lines.append(_row("probability", "NOT MEASURED"))
    elif not f.vad.emitted:
        lines.append(_row("end-of-turn signal", "NONE — step_with_extra_heads returned no heads"))
        lines.append(_row("probability", "n/a"))
    else:
        v = f.vad
        lines.append(
            _row(
                "end-of-turn signal",
                "YES — " + str(v.head_count) + " extra heads over " + str(v.samples) + " steps",
            )
        )
        lines.append(_row("probability", "YES — one float per head per 80 ms step"))
        for index, stat in v.stats.items():
            marker = "  <- upstream reads this one" if index == v.head_index else ""
            stat_line = (
                "p50 "
                + format(stat["p50"], ".3f")
                + "  p95 "
                + format(stat["p95"], ".3f")
                + "  max "
                + format(stat["max"], ".3f")
                + marker
            )
            lines.append(_row("  head[" + str(index) + "]", stat_line))
        lines.append("")
        lines.append("  rising edges of head[" + str(v.head_index) + "] — tunes the 0.5 guess:")
        for threshold, crossings in v.crossings.items():
            lines.append(_row("  > " + threshold, str(len(crossings)) + " crossings"))
        first = next(iter(v.crossings.values()), [])
        if first:
            lines.append("")
            lines.append("  where the lowest threshold fired, and the word it followed:")
            for crossing in first[:10]:
                detail = (
                    str(crossing.stream_ms).rjust(7)
                    + " ms  p="
                    + format(crossing.probability, ".3f")
                    + "  after "
                    + crossing.preceding_word
                )
                lines.append(_row("", detail))
    lines += [
        "",
        "  Maps onto tech spec 9.1 as WordEvent(text, start_ms, end_ms=inferred,",
        "  confidence=None) and EndOfTurnEvent(at_ms, probability=head value).",
        "  Anything the segmenter needs that is missing above has to be",
        "  synthesised by the adapter, which is Slice 4's job, not this spike's.",
    ]
    return lines


def _footer(f: Findings) -> list[str]:
    lines = ["", THIN, "ARTIFACTS AND CAVEATS", THIN]
    for name, path in f.artifacts.items():
        lines.append(_row(name, path))
    lines += [
        "",
        "  Not measured here, deliberately: French WER (A-10 — needs a reference",
        "  transcript; Slice 4), concurrent streams (A-3) and GPU capacity (A-4),",
        "  which are properties of moshi-server and belong to Spike B2.",
        "  Run-to-run determinism was not checked: the text sampler is greedy but",
        "  the audio sampler is not, so a second run may differ. If a number above",
        "  decides something, run the script twice and compare.",
    ]
    return lines
