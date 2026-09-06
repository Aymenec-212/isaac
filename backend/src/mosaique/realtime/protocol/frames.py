"""Binary audio frame codec (tech spec 7.1, 8.3).

Wire layout, little-endian throughout:

    [u8 version=1][u32 seq][u32 capture_ms][s16le PCM x 1920]
     1 byte        4 bytes  4 bytes         3840 bytes        = 3849 total

The 9-byte header plus a 3840-byte payload is why both 3840 and 3849 appear in
the specification; blueprint X-15 records that they are consistent, and the
gateway rejects any binary frame that is not exactly 3849 bytes.

`capture_ms` is decoded and carried for duplicate and gap diagnostics only. It
is never trusted for ordering and never written to a durable timestamp
(ADR-11 / blueprint D-02).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import StrEnum

from mosaique.speech.interfaces import FRAME_PAYLOAD_BYTES

PROTOCOL_VERSION = 1
HEADER_FORMAT = "<BII"
HEADER_BYTES = struct.calcsize(HEADER_FORMAT)  # 9
FRAME_TOTAL_BYTES = HEADER_BYTES + FRAME_PAYLOAD_BYTES  # 3849


class FrameRejection(StrEnum):
    """Reasons a frame is refused, used as the `audio_frames_rejected` label."""

    WRONG_SIZE = "wrong_size"
    BAD_VERSION = "bad_version"
    DUPLICATE_SEQUENCE = "duplicate_sequence"
    MEETING_NOT_LIVE = "meeting_not_live"


class InvalidFrame(ValueError):
    def __init__(self, reason: FrameRejection, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


@dataclass(frozen=True)
class AudioFrame:
    version: int
    sequence: int
    capture_ms: int
    pcm: bytes


def encode_frame(sequence: int, capture_ms: int, pcm: bytes) -> bytes:
    if len(pcm) != FRAME_PAYLOAD_BYTES:
        raise InvalidFrame(
            FrameRejection.WRONG_SIZE,
            f"payload must be {FRAME_PAYLOAD_BYTES} bytes, got {len(pcm)}",
        )
    return struct.pack(HEADER_FORMAT, PROTOCOL_VERSION, sequence, capture_ms) + pcm


def decode_frame(raw: bytes) -> AudioFrame:
    """Parse and validate shape. Sequence ordering is the session's business."""
    if len(raw) != FRAME_TOTAL_BYTES:
        raise InvalidFrame(
            FrameRejection.WRONG_SIZE,
            f"frame must be {FRAME_TOTAL_BYTES} bytes, got {len(raw)}",
        )
    version, sequence, capture_ms = struct.unpack_from(HEADER_FORMAT, raw, 0)
    if version != PROTOCOL_VERSION:
        raise InvalidFrame(FrameRejection.BAD_VERSION, f"unsupported frame version {version}")
    return AudioFrame(
        version=version,
        sequence=sequence,
        capture_ms=capture_ms,
        pcm=raw[HEADER_BYTES:],
    )
