"""Getting a real recording into the replay harness (Slice 4).

Pure file handling, so it belongs in the fast suite rather than behind the
integration marker: no database, no server, no model.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from tools.replay.fixtures import WrongAudioFormat, frame_count, wav_to_canonical_pcm
from tools.replay.scenario import Scenario

from mosaique.speech.interfaces import FRAME_PAYLOAD_BYTES, SAMPLE_RATE_HZ

SCENARIOS = Path(__file__).resolve().parents[2] / "tools" / "replay" / "scenarios"


def write_wav(path: Path, *, channels: int, rate: int, seconds: float = 1.0) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x02" * int(rate * seconds) * channels)
    return path


def test_a_canonical_wav_converts_to_frames_the_gateway_accepts(tmp_path):
    pcm = wav_to_canonical_pcm(write_wav(tmp_path / "fr.wav", channels=1, rate=SAMPLE_RATE_HZ))

    assert len(pcm) == SAMPLE_RATE_HZ * 2
    assert frame_count(pcm) == 13  # 24000 samples / 1920, rounded up
    assert len(pcm) % FRAME_PAYLOAD_BYTES != 0  # the ragged tail is padded on read


@pytest.mark.parametrize(("channels", "rate"), [(2, SAMPLE_RATE_HZ), (1, 48_000), (2, 44_100)])
def test_a_recording_in_the_wrong_format_is_refused_with_the_fix(tmp_path, channels, rate):
    """Resampling here would put a converter between the microphone and the
    latency number Slice 4 exists to measure. Refuse, and say how to fix it."""
    source = write_wav(tmp_path / "wrong.wav", channels=channels, rate=rate)

    with pytest.raises(WrongAudioFormat, match="ffmpeg"):
        wav_to_canonical_pcm(source)


def test_the_smoke_scenario_is_a_single_stream_at_real_time():
    """Slice 4's exit gate is a 1x single-stream replay; the scenario says so."""
    scenario = Scenario.load(SCENARIOS / "french-real.json")

    assert scenario.speed == 1.0
    assert len(scenario.participants) == 1
    assert scenario.participants[0].pcm is not None


def test_the_existing_two_participant_scenario_still_loads():
    """The fake path stays exactly as Slice 2 left it."""
    scenario = Scenario.load(SCENARIOS / "two-participants.json")

    assert len(scenario.participants) == 2
