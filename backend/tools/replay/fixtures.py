"""PCM fixtures for the replay harness.

A fixture is raw headerless audio in the one format the gateway accepts:
24 kHz signed 16-bit mono (tech spec 8.1). Real French recordings arrive in
Slice 4. Until the recognizer is real the *content* of the bytes changes
nothing — `FakeRecognizer` reads a script, not the audio — so a scenario may
ask for synthetic audio rather than make the repository carry megabytes of PCM
that prove nothing.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Iterator
from pathlib import Path

from mosaique.speech.interfaces import FRAME_PAYLOAD_BYTES, SAMPLE_RATE_HZ


def synthetic_pcm(duration_ms: int, *, seed: int = 1) -> bytes:
    """Deterministic speech-shaped tone. Same seed, same bytes, every run."""
    samples = duration_ms * SAMPLE_RATE_HZ // 1000
    fundamental = 110.0 + 37.0 * (seed % 8)
    buffer = array("h", bytes(samples * 2))
    for i in range(samples):
        t = i / SAMPLE_RATE_HZ
        value = (
            0.45 * math.sin(2 * math.pi * fundamental * t)
            + 0.25 * math.sin(2 * math.pi * fundamental * 2 * t)
            # A slow envelope so the waveform looks like speech in a plot
            # rather than a test tone.
        ) * (0.55 + 0.45 * math.sin(2 * math.pi * 0.7 * t))
        buffer[i] = int(max(-1.0, min(1.0, value)) * 12000)
    return buffer.tobytes()


def load_pcm(path: Path) -> bytes:
    """Read a raw fixture, padding a ragged tail to a whole frame."""
    raw = path.read_bytes()
    remainder = len(raw) % FRAME_PAYLOAD_BYTES
    return raw if remainder == 0 else raw + b"\x00" * (FRAME_PAYLOAD_BYTES - remainder)


def iter_frames(pcm: bytes) -> Iterator[bytes]:
    """Split into canonical 80 ms frames, padding the last one with silence."""
    for offset in range(0, len(pcm), FRAME_PAYLOAD_BYTES):
        chunk = pcm[offset : offset + FRAME_PAYLOAD_BYTES]
        if len(chunk) < FRAME_PAYLOAD_BYTES:
            chunk += b"\x00" * (FRAME_PAYLOAD_BYTES - len(chunk))
        yield chunk


def frame_count(pcm: bytes) -> int:
    return (len(pcm) + FRAME_PAYLOAD_BYTES - 1) // FRAME_PAYLOAD_BYTES
