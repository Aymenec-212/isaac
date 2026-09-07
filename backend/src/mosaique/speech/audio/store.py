"""Raw per-participant audio storage (ADR-06).

One headerless file per `AudioSession`, holding exactly the canonical frames
the recognizer was given: 24 kHz signed 16-bit mono, silence padding included.
Writing the padding is what keeps the file aligned with the ADR-11 timeline, so

    byte_offset = session_ms * BYTES_PER_MS

is exact and FR-11 timestamp navigation needs no index table.

Retention and consent are still open (Q3); nothing here deletes anything.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from mosaique.speech.interfaces import BYTES_PER_SAMPLE, SAMPLE_RATE_HZ

BYTES_PER_MS = SAMPLE_RATE_HZ * BYTES_PER_SAMPLE // 1000  # 48


@runtime_checkable
class AudioStore(Protocol):
    """Where a participant's raw PCM goes. The runtime knows nothing more."""

    def object_key(self, meeting_id: str, audio_session_id: str) -> str:
        """Durable locator recorded on the `AudioSession` row."""
        ...

    def open_session(self, meeting_id: str, audio_session_id: str) -> BinaryIO:
        """Open the sink for one audio session. The caller closes it."""
        ...


class LocalAudioStore:
    """Files under a root directory. Object storage replaces this in Slice 7."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def object_key(self, meeting_id: str, audio_session_id: str) -> str:
        return f"{meeting_id}/{audio_session_id}.pcm"

    def open_session(self, meeting_id: str, audio_session_id: str) -> BinaryIO:
        path = self._root / self.object_key(meeting_id, audio_session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("wb")


class NullAudioStore:
    """Discards audio. Used by tests and the replay harness.

    It keeps `object_key` identical to the local store so the persisted row has
    the same shape either way; only the bytes go nowhere. Writes are discarded
    rather than buffered because an accelerated hour-long replay would
    otherwise accumulate a couple of hundred megabytes for nothing.
    """

    def object_key(self, meeting_id: str, audio_session_id: str) -> str:
        return f"{meeting_id}/{audio_session_id}.pcm"

    def open_session(self, meeting_id: str, audio_session_id: str) -> BinaryIO:
        return open(os.devnull, "wb")
