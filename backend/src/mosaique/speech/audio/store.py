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
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from mosaique.speech.interfaces import BYTES_PER_SAMPLE, SAMPLE_RATE_HZ

BYTES_PER_MS = SAMPLE_RATE_HZ * BYTES_PER_SAMPLE // 1000  # 48

# 64 KiB is ~1.4 s of canonical audio: small enough that a seek does not
# allocate a meeting, large enough not to syscall per frame.
READ_CHUNK_BYTES = 64 * 1024


@runtime_checkable
class AudioStore(Protocol):
    """Where a participant's raw PCM goes. The runtime knows nothing more."""

    def object_key(self, meeting_id: str, audio_session_id: str) -> str:
        """Durable locator recorded on the `AudioSession` row."""
        ...

    def open_session(self, meeting_id: str, audio_session_id: str) -> BinaryIO:
        """Open the sink for one audio session. The caller closes it."""
        ...

    def size_bytes(self, object_key: str) -> int | None:
        """Bytes stored under this key, or None when there is nothing there.

        Separate from reading because a Range request has to answer
        `Content-Range: bytes a-b/total` before it streams anything, and
        because "no audio for this session" is an ordinary outcome — the null
        store discards everything, and Q3 will eventually delete files out from
        under rows that still reference them.
        """
        ...

    def read_range(self, object_key: str, start: int, length: int) -> Iterator[bytes]:
        """Yield `length` bytes from `start`, in chunks.

        An iterator rather than `bytes` so a browser seeking into a long
        meeting does not pull the whole file into memory to serve a few
        seconds of it.
        """
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

    def _resolved(self, object_key: str) -> Path | None:
        """Resolve a stored key under the root, refusing anything that escapes.

        `object_key` comes off a database row rather than from a request, so
        this is defence in depth rather than the primary check. It is here
        because the cost is three lines and the failure it prevents — a key
        containing `..` serving an arbitrary file — is the kind that only gets
        noticed once it matters.
        """
        root = self._root.resolve()
        candidate = (root / object_key).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return None
        return candidate

    def size_bytes(self, object_key: str) -> int | None:
        path = self._resolved(object_key)
        return None if path is None else path.stat().st_size

    def read_range(self, object_key: str, start: int, length: int) -> Iterator[bytes]:
        path = self._resolved(object_key)
        if path is None or length <= 0:
            return
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(READ_CHUNK_BYTES, remaining))
                if not chunk:
                    return
                remaining -= len(chunk)
                yield chunk


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

    def size_bytes(self, object_key: str) -> int | None:
        """Always None: nothing was kept, so the route answers 404 rather than
        streaming silence that would look like a recording."""
        return None

    def read_range(self, object_key: str, start: int, length: int) -> Iterator[bytes]:
        return iter(())
