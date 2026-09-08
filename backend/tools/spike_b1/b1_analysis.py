"""Pure analysis for Spike B1 — no model, no MLX, no I/O, no clock.

`probe.py` is the half of this spike that can only run on Apple silicon. This
is the half that decides what the numbers *mean*, and it is split out precisely
so it can be unit-tested on a machine that cannot run the model at all
(`tests/unit/test_spike_b1_analysis.py`).

The split matters most for the retraction detector. "Zero retractions observed"
is worth nothing unless something proves the detector can see one, so the tests
feed it a synthetic retraction and require it to fire. Without that, question 1
answers itself and the answer means nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# Tech spec 8.1. Duplicated rather than imported, because this module is also
# loaded by `probe.py` under `uv run --script`, in a throwaway environment where
# the `mosaique` package does not exist. `test_spike_b1_analysis.py` asserts
# that these still agree with `mosaique.speech.interfaces`.
SAMPLE_RATE_HZ = 24_000
FRAME_DURATION_MS = 80
SAMPLES_PER_FRAME = 1_920

# Sentencepiece marks the start of a word with U+2581 LOWER ONE EIGHTH BLOCK.
WORD_MARKER = "▁"

# ADR-13 and the B1 brief: below this factor the D-05 flush trick has no
# headroom on MLX, and A-12 is answered negatively for this runtime.
FLUSH_HEADROOM_FACTOR = 1.5

# Kyutai model-card figure for stt-1b-en_fr. Used only when config.json declares
# no delay of its own, and reported as ASSUMED when it is used.
ASSUMED_DELAY_MS = 500

# Upstream `stt_from_file_mlx.py` skips these two ids.
PADDING_TOKEN_IDS = (0, 3)


# --------------------------------------------------------------------------
# Token stream
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenEvent:
    """One text token as the runtime emitted it.

    `step` is the 80 ms frame index into the audio actually pushed, so it is
    stream time in the ADR-11 sense — derived from frame counts, never a clock.
    `wall_ms` is wall time since inference started and exists only to answer
    question 2; nothing downstream may use it for ordering.
    """

    step: int
    token_id: int
    piece: str
    wall_ms: float


@dataclass(frozen=True)
class Word:
    text: str
    start_step: int
    end_step: int
    start_ms: int
    end_ms: int
    pieces: int


def piece_text(piece: str) -> str:
    """Sentencepiece piece to plain text, the way upstream renders it."""
    return piece.replace(WORD_MARKER, " ")


def transcript_snapshots(tokens: list[TokenEvent]) -> list[str]:
    """The transcript as it stood after each emitted token."""
    snapshots: list[str] = []
    text = ""
    for token in tokens:
        text += piece_text(token.piece)
        snapshots.append(text)
    return snapshots


def _step_to_ms(step: int, delay_ms: int, silence_prefix_ms: int) -> int:
    return max(0, step * FRAME_DURATION_MS - delay_ms - silence_prefix_ms)


def assemble_words(
    tokens: list[TokenEvent],
    *,
    delay_ms: int,
    silence_prefix_ms: int = 0,
) -> list[Word]:
    """Fold sentencepiece pieces into words with stream-time bounds.

    A word begins at a piece carrying the word marker. Timing is derived from
    the step that emitted the piece, shifted back by the model delay, because
    the token for a sound arrives `delay_ms` after the sound did.
    """
    words: list[Word] = []
    open_pieces: list[str] = []
    start_step = 0
    end_step = 0

    def flush() -> None:
        nonlocal open_pieces
        if not open_pieces:
            return
        text = "".join(open_pieces).replace(WORD_MARKER, "").strip()
        if text:
            words.append(
                Word(
                    text=text,
                    start_step=start_step,
                    end_step=end_step,
                    start_ms=_step_to_ms(start_step, delay_ms, silence_prefix_ms),
                    end_ms=_step_to_ms(end_step + 1, delay_ms, silence_prefix_ms),
                    pieces=len(open_pieces),
                )
            )
        open_pieces = []

    for token in tokens:
        if token.piece.startswith(WORD_MARKER) or not open_pieces:
            flush()
            start_step = token.step
        open_pieces.append(token.piece)
        end_step = token.step
    flush()
    return words


# --------------------------------------------------------------------------
# Question 1 — retraction
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PrefixViolation:
    index: int
    before: str
    after: str


@dataclass(frozen=True)
class WordMutation:
    index: int
    position: int
    before: str
    after: str


@dataclass(frozen=True)
class RetractionReport:
    steps_observed: int
    tokens_emitted: int
    padding_steps: int
    prefix_violations: list[PrefixViolation]
    word_mutations: list[WordMutation]

    @property
    def clean(self) -> bool:
        return not self.prefix_violations and not self.word_mutations


def check_prefix_monotonic(snapshots: list[str]) -> list[PrefixViolation]:
    """Every snapshot must extend the one before it.

    This is the weakest reading of "text is not retracted", and the only one an
    append-only API can be held to. It is real code rather than a claim in prose
    because a future runtime — moshi-server over a wire protocol, say — can
    genuinely fail it.
    """
    violations: list[PrefixViolation] = []
    for index in range(1, len(snapshots)):
        if not snapshots[index].startswith(snapshots[index - 1]):
            violations.append(
                PrefixViolation(
                    index=index,
                    before=snapshots[index - 1][-60:],
                    after=snapshots[index][-60:],
                )
            )
    return violations


def check_word_stability(snapshots: list[str]) -> list[WordMutation]:
    """A word the speaker has moved past must never change.

    Stronger than the prefix check, and the one that actually decides X-14: the
    last word of a snapshot is still being built, but every word before it is
    settled, and a settled word must survive verbatim into the next snapshot.
    """
    mutations: list[WordMutation] = []
    for index in range(1, len(snapshots)):
        settled = snapshots[index - 1].split()[:-1]
        current = snapshots[index].split()
        for position, word in enumerate(settled):
            if position >= len(current):
                mutations.append(
                    WordMutation(index=index, position=position, before=word, after="<dropped>")
                )
                break
            if current[position] != word:
                mutations.append(
                    WordMutation(
                        index=index, position=position, before=word, after=current[position]
                    )
                )
                break
    return mutations


def analyse_retraction(
    tokens: list[TokenEvent], *, steps_observed: int, padding_steps: int
) -> RetractionReport:
    snapshots = transcript_snapshots(tokens)
    return RetractionReport(
        steps_observed=steps_observed,
        tokens_emitted=len(tokens),
        padding_steps=padding_steps,
        prefix_violations=check_prefix_monotonic(snapshots),
        word_mutations=check_word_stability(snapshots),
    )


# --------------------------------------------------------------------------
# Question 2 — realised speed factor
# --------------------------------------------------------------------------


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile. Empty input is 0.0, not an exception."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(q / 100 * len(ordered))))
    return ordered[rank - 1]


def speed_verdict(factor: float) -> str:
    """Three outcomes, because the sub-real-time case is not merely 'worse'.

    Above 1.5x the flush trick has room to catch up. Between 1.0x and 1.5x the
    runtime keeps up with a live meeting but has nothing spare, so D-05 buys
    nothing and A-12 is negative for MLX. Below 1.0x the runtime cannot follow a
    real conversation at all, which is a Slice 4 blocker, not an A-12 answer.
    """
    if factor >= FLUSH_HEADROOM_FACTOR:
        return "HEADROOM"
    if factor >= 1.0:
        return "MARGINAL"
    return "TOO SLOW"


VERDICT_MEANING = {
    "HEADROOM": (
        "realised >= 1.5x: flush() has room to catch up, so A-12 is\n"
        "                          answerable positively for this runtime"
    ),
    "MARGINAL": (
        "1.0x <= realised < 1.5x: keeps up with a live meeting but\n"
        "                          has nothing spare, so D-05 buys nothing on MLX\n"
        "                          and A-12 is answered NEGATIVELY here"
    ),
    "TOO SLOW": (
        "realised < 1.0x: cannot follow a real conversation on this\n"
        "                          machine at all — a Slice 4 blocker, not just an\n"
        "                          A-12 answer"
    ),
}


@dataclass(frozen=True)
class SpeedReport:
    fixture_ms: int
    pushed_ms: int
    steps: int
    load_s: float
    warmup_s: float
    inference_s: float
    step_ms: list[float] = field(default_factory=list, repr=False)

    @property
    def realised_factor(self) -> float:
        if self.inference_s <= 0:
            return 0.0
        return (self.pushed_ms / 1000.0) / self.inference_s

    @property
    def fixture_factor(self) -> float:
        if self.inference_s <= 0:
            return 0.0
        return (self.fixture_ms / 1000.0) / self.inference_s

    @property
    def steps_over_budget(self) -> int:
        return sum(1 for ms in self.step_ms if ms > FRAME_DURATION_MS)

    @property
    def verdict(self) -> str:
        return speed_verdict(self.realised_factor)


# --------------------------------------------------------------------------
# Question 3 — quantization and model identity
# --------------------------------------------------------------------------


def quantization_from_weights(filename: str) -> str:
    """Mirror the upstream loader exactly: it infers bits from the filename."""
    name = filename.lower()
    if name.endswith(".q4.safetensors"):
        return "q4"
    if name.endswith(".q8.safetensors"):
        return "q8"
    return "bf16"


def model_id_from_repo(hf_repo: str) -> str:
    """`kyutai/stt-1b-en_fr-mlx` -> `kyutai/stt-1b-en_fr`.

    The runtime suffix is stripped because ADR-13 consequence 3 wants runtime
    and quantization after the `@`, not smuggled into the model name.
    """
    for suffix in ("-mlx", "-candle", "-pytorch"):
        if hf_repo.endswith(suffix):
            return hf_repo[: -len(suffix)]
    return hf_repo


def asr_version(hf_repo: str, *, runtime: str, quantization: str) -> str:
    """The string ADR-13 consequence 3 requires in `Meeting.asr_version`."""
    return f"{model_id_from_repo(hf_repo)}@{runtime}-{quantization}"


def _find_numeric(config: dict[str, Any], needle: str) -> tuple[float, str] | None:
    """Breadth-first search for a numeric key whose name contains `needle`."""
    queue: list[tuple[dict[str, Any], str]] = [(config, "config")]
    while queue:
        node, path = queue.pop(0)
        nested: list[tuple[dict[str, Any], str]] = []
        for key, value in node.items():
            here = path + "." + str(key)
            if isinstance(value, dict):
                nested.append((value, here))
            elif (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and needle in str(key).lower()
            ):
                return float(value), here
        queue.extend(nested)
    return None


def _seconds_field(config: dict[str, Any], needle: str) -> tuple[float, str, bool] | None:
    """A numeric config field whose name says it is in seconds.

    The unit check is the point. Kyutai configs carry several fields with
    "delay" in the name that are counts of frames, not durations, and reading
    one of those as seconds would shift every word timestamp by seconds. So a
    match whose name does not say "second" is returned flagged, and the caller
    refuses to convert it.
    """
    found = _find_numeric(config, needle)
    if found is None:
        return None
    value, path = found
    return value, path, "second" in path.rsplit(".", 1)[-1].lower()


def discover_delay_ms(config: dict[str, Any]) -> tuple[int, str]:
    """Whatever the build reports, or a loudly-labelled assumption."""
    found = _seconds_field(config, "delay")
    if found is None:
        return ASSUMED_DELAY_MS, "ASSUMED (model card; config.json declares no delay)"
    value, path, in_seconds = found
    if not in_seconds:
        return ASSUMED_DELAY_MS, (
            "ASSUMED (model card). config.json has " + path + " = " + str(value) + ", but its "
            "name does not say seconds, so it was NOT used — check it by hand"
        )
    return int(round(value * 1000)), path + " = " + str(value) + " s"


def discover_silence_prefix_ms(config: dict[str, Any]) -> tuple[int, str]:
    found = _seconds_field(config, "silence_prefix")
    if found is None:
        return 0, "config.json declares none"
    value, path, in_seconds = found
    if not in_seconds:
        return 0, (
            "config.json has " + path + " = " + str(value) + ", but its name does not say "
            "seconds, so it was NOT used — check it by hand"
        )
    return int(round(value * 1000)), path + " = " + str(value) + " s"


@dataclass(frozen=True)
class ModelIdentity:
    hf_repo: str
    revision: str
    weights_file: str
    weights_blob: str
    weights_bytes: int
    mimi_file: str
    tokenizer_file: str
    quantization: str
    runtime: str
    delay_ms: int
    delay_source: str
    silence_prefix_ms: int
    silence_prefix_source: str

    @property
    def asr_version(self) -> str:
        return asr_version(self.hf_repo, runtime=self.runtime, quantization=self.quantization)


# --------------------------------------------------------------------------
# Question 4 — event shape
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class VadSample:
    step: int
    heads: tuple[float, ...]


@dataclass(frozen=True)
class VadCrossing:
    step: int
    stream_ms: int
    probability: float
    preceding_word: str


@dataclass(frozen=True)
class VadReport:
    head_count: int
    head_index: int
    samples: int
    stats: dict[int, dict[str, float]]
    crossings: dict[str, list[VadCrossing]]

    @property
    def emitted(self) -> bool:
        return self.head_count > 0


def nearest_word_before(words: list[Word], stream_ms: int) -> str:
    chosen = ""
    for word in words:
        if word.start_ms <= stream_ms:
            chosen = word.text
        else:
            break
    return chosen


def rising_edges(
    samples: list[VadSample],
    *,
    head_index: int,
    threshold: float,
    delay_ms: int,
    silence_prefix_ms: int,
    words: list[Word],
) -> list[VadCrossing]:
    """Only rising edges: an end of turn is an event, not a sustained level."""
    crossings: list[VadCrossing] = []
    above = False
    for sample in samples:
        if head_index >= len(sample.heads):
            continue
        value = sample.heads[head_index]
        if value > threshold and not above:
            stream_ms = _step_to_ms(sample.step, delay_ms, silence_prefix_ms)
            crossings.append(
                VadCrossing(
                    step=sample.step,
                    stream_ms=stream_ms,
                    probability=value,
                    preceding_word=nearest_word_before(words, stream_ms),
                )
            )
        above = value > threshold
    return crossings


def analyse_vad(
    samples: list[VadSample],
    *,
    head_index: int,
    thresholds: tuple[float, ...],
    delay_ms: int,
    silence_prefix_ms: int,
    words: list[Word],
) -> VadReport:
    head_count = max((len(s.heads) for s in samples), default=0)
    stats: dict[int, dict[str, float]] = {}
    for index in range(head_count):
        values = [s.heads[index] for s in samples if index < len(s.heads)]
        stats[index] = {
            "p50": percentile(values, 50),
            "p95": percentile(values, 95),
            "max": max(values) if values else 0.0,
        }
    crossings = {
        format(threshold, ".2f"): rising_edges(
            samples,
            head_index=head_index,
            threshold=threshold,
            delay_ms=delay_ms,
            silence_prefix_ms=silence_prefix_ms,
            words=words,
        )
        for threshold in thresholds
    }
    return VadReport(
        head_count=head_count,
        head_index=head_index,
        samples=len(samples),
        stats=stats,
        crossings=crossings,
    )
