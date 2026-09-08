"""What Spike B1 concludes, tested on a machine that cannot run the model.

The spike itself needs Apple silicon. Everything that turns its token log into
an answer does not, and that half lives in `tools/spike_b1/b1_analysis.py`
precisely so it can be tested here.

The retraction tests are the ones that matter. B1's first question is "does
emitted text ever change after it is emitted", and the expected answer is no —
which makes a detector that cannot detect anything indistinguishable from a
correct one. So the detector is fed a retraction and required to fire.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[2] / "tools" / "spike_b1"
if str(SPIKE_DIR) not in sys.path:
    # The same insertion `probe.py` performs: the spike is a standalone PEP 723
    # script, not an installed package, because ADR-13 consequence 5 keeps MLX
    # out of the backend's dependency graph.
    sys.path.insert(0, str(SPIKE_DIR))

import b1_analysis as ana  # noqa: E402
import b1_summary as summary  # noqa: E402


def tokens(*pieces: str, step: int = 0, stride: int = 2) -> list[ana.TokenEvent]:
    return [
        ana.TokenEvent(step=step + i * stride, token_id=100 + i, piece=piece, wall_ms=float(i))
        for i, piece in enumerate(pieces)
    ]


# --------------------------------------------------------------------------
# The canonical frame, and the duplication that pays for it
# --------------------------------------------------------------------------


def test_the_spike_agrees_with_the_canonical_audio_format():
    """`b1_analysis` re-declares spec 8.1 because it runs without `mosaique`.

    That duplication is only safe while the two agree, so this is the test that
    makes it safe.
    """
    from mosaique.speech.interfaces import (
        FRAME_DURATION_MS,
        SAMPLE_RATE_HZ,
        SAMPLES_PER_FRAME,
    )

    assert ana.SAMPLE_RATE_HZ == SAMPLE_RATE_HZ
    assert ana.FRAME_DURATION_MS == FRAME_DURATION_MS
    assert ana.SAMPLES_PER_FRAME == SAMPLES_PER_FRAME


# --------------------------------------------------------------------------
# Question 1 — retraction
# --------------------------------------------------------------------------


def test_an_append_only_stream_reports_no_retraction():
    log = tokens("▁Bonjour", "▁tout", "▁le", "▁monde")
    report = ana.analyse_retraction(log, steps_observed=100, padding_steps=96)

    assert report.clean
    assert report.tokens_emitted == 4
    assert report.prefix_violations == []
    assert report.word_mutations == []


def test_the_detector_sees_a_transcript_that_stops_extending():
    """A runtime that rewrites its transcript must not pass as append-only."""
    violations = ana.check_prefix_monotonic([" Bonjour", " Bonjour tout", " Bonjour tous les"])

    assert len(violations) == 1
    assert violations[0].index == 2


def test_growing_the_last_word_is_not_a_prefix_violation():
    """Why the word-level check exists at all.

    " tout" becoming " toute" extends the character stream, so the prefix check
    is right to stay quiet. Only `check_word_stability` can tell that apart from
    a correction, and only because it knows the last word is still open.
    """
    assert ana.check_prefix_monotonic([" Bonjour tout", " Bonjour toute"]) == []


def test_the_detector_sees_a_word_the_speaker_had_already_moved_past_change():
    mutations = ana.check_word_stability([" le budget est validé", " le budjet est validé"])

    assert [m.position for m in mutations] == [1]
    assert mutations[0].before == "budget"
    assert mutations[0].after == "budjet"


def test_changing_the_word_still_being_spoken_is_not_a_mutation():
    assert ana.check_word_stability([" le budget est", " le budget était"]) == []


def test_a_word_still_being_built_may_change_without_counting_as_retraction():
    """The last word of a snapshot is open; only settled words are held to."""
    assert ana.check_word_stability([" le bud", " le budget"]) == []


def test_a_dropped_word_counts_as_retraction():
    mutations = ana.check_word_stability([" le budget est validé", " le"])

    assert len(mutations) == 1
    assert mutations[0].after == "<dropped>"


# --------------------------------------------------------------------------
# Word assembly and timing
# --------------------------------------------------------------------------


def test_pieces_fold_into_words_at_the_sentencepiece_marker():
    log = [
        ana.TokenEvent(step=10, token_id=1, piece="▁budget", wall_ms=0.0),
        ana.TokenEvent(step=12, token_id=2, piece="▁trimes", wall_ms=0.0),
        ana.TokenEvent(step=13, token_id=3, piece="triel", wall_ms=0.0),
    ]

    words = ana.assemble_words(log, delay_ms=500)

    assert [w.text for w in words] == ["budget", "trimestriel"]
    assert [w.pieces for w in words] == [1, 2]


def test_a_word_is_timed_from_its_first_frame_less_the_model_delay():
    """The token for a sound arrives `delay_ms` after the sound did (ADR-11)."""
    log = [ana.TokenEvent(step=20, token_id=1, piece="▁vendredi", wall_ms=0.0)]

    word = ana.assemble_words(log, delay_ms=500)[0]

    assert word.start_ms == 20 * 80 - 500  # 1100
    assert word.end_ms == 21 * 80 - 500  # 1180


def test_a_word_never_lands_before_the_start_of_the_stream():
    log = [ana.TokenEvent(step=1, token_id=1, piece="▁oui", wall_ms=0.0)]

    assert ana.assemble_words(log, delay_ms=500)[0].start_ms == 0


def test_a_silence_prefix_shifts_words_back_onto_the_recording():
    log = [ana.TokenEvent(step=30, token_id=1, piece="▁oui", wall_ms=0.0)]

    word = ana.assemble_words(log, delay_ms=500, silence_prefix_ms=1_000)[0]

    assert word.start_ms == 30 * 80 - 500 - 1_000  # 900


# --------------------------------------------------------------------------
# Question 2 — speed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factor", "expected"),
    [
        (4.0, "HEADROOM"),
        (1.5, "HEADROOM"),
        (1.49, "MARGINAL"),
        (1.0, "MARGINAL"),
        (0.9, "TOO SLOW"),
    ],
)
def test_the_flush_headroom_verdict_has_three_outcomes(factor, expected):
    assert ana.speed_verdict(factor) == expected


def test_the_realised_factor_is_audio_pushed_over_inference_time():
    report = ana.SpeedReport(
        fixture_ms=90_000,
        pushed_ms=92_000,
        steps=1_150,
        load_s=12.0,
        warmup_s=2.0,
        inference_s=46.0,
        step_ms=[40.0] * 1_149 + [200.0],
    )

    assert report.realised_factor == pytest.approx(2.0)
    assert report.fixture_factor == pytest.approx(90_000 / 1000 / 46.0)
    assert report.steps_over_budget == 1
    assert report.verdict == "HEADROOM"


def test_loading_the_model_is_not_charged_against_the_speed_factor():
    """Load and warmup are startup cost, not throughput."""
    report = ana.SpeedReport(
        fixture_ms=10_000,
        pushed_ms=10_000,
        steps=125,
        load_s=600.0,
        warmup_s=60.0,
        inference_s=5.0,
    )

    assert report.realised_factor == pytest.approx(2.0)


def test_percentiles_use_nearest_rank():
    values = [float(n) for n in range(1, 11)]

    assert ana.percentile(values, 50) == 5.0
    assert ana.percentile(values, 95) == 10.0
    assert ana.percentile(values, 100) == 10.0
    assert ana.percentile([], 95) == 0.0


# --------------------------------------------------------------------------
# Question 3 — identity
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("model.q4.safetensors", "q4"),
        ("model.q8.safetensors", "q8"),
        ("model.safetensors", "bf16"),
    ],
)
def test_quantization_is_read_the_way_the_loader_reads_it(filename, expected):
    assert ana.quantization_from_weights(filename) == expected


def test_asr_version_names_the_runtime_and_the_quantization():
    """ADR-13 consequence 3, verbatim: MLX-era and CUDA-era rows must differ."""
    mlx = ana.asr_version("kyutai/stt-1b-en_fr-mlx", runtime="mlx", quantization="q4")
    cuda = ana.asr_version("kyutai/stt-1b-en_fr", runtime="moshi-server", quantization="bf16")

    assert mlx == "kyutai/stt-1b-en_fr@mlx-q4"
    assert cuda == "kyutai/stt-1b-en_fr@moshi-server-bf16"
    assert mlx != cuda


def test_the_delay_is_read_from_the_build_when_the_build_declares_one():
    delay_ms, source = ana.discover_delay_ms(
        {"stt_config": {"audio_delay_seconds": 0.5, "audio_silence_prefix_seconds": 1.0}}
    )

    assert delay_ms == 500
    assert "stt_config.audio_delay_seconds" in source
    assert "ASSUMED" not in source


def test_an_assumed_delay_says_so_in_the_line_that_reports_it():
    delay_ms, source = ana.discover_delay_ms({"model_type": "stt"})

    assert delay_ms == ana.ASSUMED_DELAY_MS
    assert source.startswith("ASSUMED")


def test_the_silence_prefix_is_read_from_the_build_too():
    prefix_ms, source = ana.discover_silence_prefix_ms(
        {"stt_config": {"audio_silence_prefix_seconds": 1.0}}
    )

    assert prefix_ms == 1_000
    assert "audio_silence_prefix_seconds" in source


# --------------------------------------------------------------------------
# Question 4 — event shape
# --------------------------------------------------------------------------


def test_only_rising_edges_of_the_vad_head_count_as_an_end_of_turn():
    """A sustained high probability is one turn ending, not fifty."""
    samples = [
        ana.VadSample(step=step, heads=(0.0, 0.0, value))
        for step, value in enumerate([0.1, 0.9, 0.95, 0.92, 0.1, 0.8])
    ]

    crossings = ana.rising_edges(
        samples, head_index=2, threshold=0.5, delay_ms=0, silence_prefix_ms=0, words=[]
    )

    assert [c.step for c in crossings] == [1, 5]


def test_a_crossing_names_the_word_it_followed():
    words = ana.assemble_words(
        tokens("▁commencer", step=0, stride=1) + tokens("▁validé", step=20, stride=1),
        delay_ms=0,
    )
    samples = [ana.VadSample(step=25, heads=(0.0, 0.0, 0.9))]

    crossing = ana.rising_edges(
        samples, head_index=2, threshold=0.5, delay_ms=0, silence_prefix_ms=0, words=words
    )[0]

    assert crossing.preceding_word == "validé"


def test_the_vad_analysis_reports_every_head_not_only_the_one_upstream_reads():
    samples = [ana.VadSample(step=s, heads=(0.1, 0.2, 0.3, 0.4)) for s in range(10)]

    report = ana.analyse_vad(
        samples,
        head_index=2,
        thresholds=(0.5,),
        delay_ms=0,
        silence_prefix_ms=0,
        words=[],
    )

    assert report.emitted
    assert report.head_count == 4
    assert set(report.stats) == {0, 1, 2, 3}


def test_a_runtime_that_emits_no_heads_is_reported_as_emitting_none():
    report = ana.analyse_vad(
        [], head_index=2, thresholds=(0.5,), delay_ms=0, silence_prefix_ms=0, words=[]
    )

    assert not report.emitted


# --------------------------------------------------------------------------
# The pasteable block itself
# --------------------------------------------------------------------------


def _findings(**overrides):
    log = tokens("▁Bonjour", "▁tout", "▁le", "▁monde")
    identity = ana.ModelIdentity(
        hf_repo="kyutai/stt-1b-en_fr-mlx",
        revision="abc123",
        weights_file="model.q4.safetensors",
        weights_blob="blob",
        weights_bytes=1_000_000_000,
        mimi_file="mimi.safetensors",
        tokenizer_file="tokenizer.model",
        quantization="q4",
        runtime="mlx",
        delay_ms=500,
        delay_source="config.stt_config.audio_delay_seconds = 0.5 s",
        silence_prefix_ms=0,
        silence_prefix_source="config.json declares none",
    )
    defaults = dict(
        env={"generated": "2026-09-08T00:00:00Z"},
        fixture={
            "path": "fr.wav",
            "fixture_ms": 90_000,
            "pushed_ms": 92_000,
            "frames": 1_150,
            "trailing_silence_ms": 2_000,
            "channels_mixed": False,
        },
        identity=identity,
        speed=ana.SpeedReport(
            fixture_ms=90_000,
            pushed_ms=92_000,
            steps=1_150,
            load_s=1.0,
            warmup_s=1.0,
            inference_s=46.0,
            step_ms=[40.0] * 1_150,
        ),
        retraction=ana.analyse_retraction(log, steps_observed=1_150, padding_steps=1_146),
        tokens=log,
        words=ana.assemble_words(log, delay_ms=500),
        config_text='{"mimi_name": "mimi.safetensors"}',
        vad_skipped_because="--no-vad-pass was given",
    )
    defaults.update(overrides)
    return summary.Findings(**defaults)


def test_the_summary_answers_all_four_questions_and_nothing_else():
    """Four numbered answers, in order, and no fifth thing dressed as one."""
    block = summary.render(_findings())
    headings = re.findall(r"^(\d)\. (.+)$", block, flags=re.MULTILINE)

    assert [number for number, _ in headings] == ["1", "2", "3", "4"]
    assert "RETRACTION" in headings[0][1]
    assert "REALISED SPEED FACTOR" in headings[1][1]
    assert "QUANTIZATION AND MODEL IDENTITY" in headings[2][1]
    assert "EVENT SHAPE" in headings[3][1]


def test_the_summary_carries_the_numbers_a_decision_needs():
    block = summary.render(_findings())

    assert "NO RETRACTION OBSERVED" in block
    assert "2.00x" in block
    assert "HEADROOM" in block
    assert "kyutai/stt-1b-en_fr@mlx-q4" in block
    assert "NOT MEASURED" in block  # the VAD pass was skipped, and it says so


def test_a_retraction_is_impossible_to_miss_in_the_summary():
    retracted = ana.RetractionReport(
        steps_observed=10,
        tokens_emitted=3,
        padding_steps=7,
        prefix_violations=[ana.PrefixViolation(index=2, before="le budget", after="la budget")],
        word_mutations=[
            ana.WordMutation(index=2, position=0, before="le", after="la"),
        ],
    )

    block = summary.render(_findings(retraction=retracted))

    assert "RETRACTION OBSERVED" in block
    assert "NO RETRACTION OBSERVED" not in block


def test_self_check_output_cannot_be_mistaken_for_a_measurement():
    block = summary.render(_findings(self_check=True))

    assert block.count("SELF-CHECK OUTPUT") == 2
    assert "NOT A MEASUREMENT" in block


def test_a_delay_field_that_is_not_in_seconds_is_refused_rather_than_converted():
    """Kyutai configs carry frame-count "delays" too. Reading one as seconds
    would shift every word timestamp by seconds, so it is not read at all."""
    delay_ms, source = ana.discover_delay_ms({"depformer": {"delay": 2}})

    assert delay_ms == ana.ASSUMED_DELAY_MS
    assert source.startswith("ASSUMED")
    assert "NOT used" in source


def test_a_silence_prefix_that_is_not_in_seconds_is_refused_too():
    prefix_ms, source = ana.discover_silence_prefix_ms({"silence_prefix": 24})

    assert prefix_ms == 0
    assert "NOT used" in source
