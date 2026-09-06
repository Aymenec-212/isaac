"""Binary frame codec and validation (tech spec 7.1, 8.3; blueprint X-15)."""

from __future__ import annotations

import pytest

from mosaique.realtime.protocol.frames import (
    FRAME_TOTAL_BYTES,
    HEADER_BYTES,
    FrameRejection,
    InvalidFrame,
    decode_frame,
    encode_frame,
)
from mosaique.speech.interfaces import FRAME_PAYLOAD_BYTES

PCM = b"\x01\x02" * 1920


def test_frame_arithmetic_matches_the_specification():
    """3840 payload + 9 header = 3849. Both numbers appear in the spec."""
    assert FRAME_PAYLOAD_BYTES == 3840
    assert HEADER_BYTES == 9
    assert FRAME_TOTAL_BYTES == 3849


def test_roundtrip_preserves_every_field():
    frame = decode_frame(encode_frame(sequence=42, capture_ms=3360, pcm=PCM))
    assert (frame.version, frame.sequence, frame.capture_ms) == (1, 42, 3360)
    assert frame.pcm == PCM


def test_encoded_frame_is_exactly_3849_bytes():
    assert len(encode_frame(0, 0, PCM)) == FRAME_TOTAL_BYTES


@pytest.mark.parametrize("size", [0, 3848, 3850, 4096])
def test_wrong_size_is_rejected(size):
    with pytest.raises(InvalidFrame) as exc:
        decode_frame(b"\x00" * size)
    assert exc.value.reason is FrameRejection.WRONG_SIZE


def test_unsupported_version_is_rejected():
    raw = bytearray(encode_frame(1, 0, PCM))
    raw[0] = 9
    with pytest.raises(InvalidFrame) as exc:
        decode_frame(bytes(raw))
    assert exc.value.reason is FrameRejection.BAD_VERSION


def test_short_payload_cannot_be_encoded():
    with pytest.raises(InvalidFrame):
        encode_frame(0, 0, b"\x00" * 100)


def test_large_sequence_and_capture_survive_the_u32_fields():
    frame = decode_frame(encode_frame(4_000_000_000, 4_000_000_000, PCM))
    assert frame.sequence == 4_000_000_000
