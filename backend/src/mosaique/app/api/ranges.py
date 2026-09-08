"""HTTP Range parsing for audio scrubbing (tech spec 6, FR-11).

A separate module because seeking is arithmetic and arithmetic deserves tests
that do not need a server. Browsers drive this hard: `<audio>` issues an
open-ended `bytes=0-` probe, then a fresh request for every seek, and a wrong
`Content-Range` header shows up as a scrub bar that silently refuses to move
rather than as an error anyone can see.

Only the single-range form is supported. Multi-range replies need multipart
encoding, no browser media element asks for one, and answering 200 with the
whole body is a legal response to a range we choose not to honour.
"""

from __future__ import annotations

from dataclasses import dataclass

UNIT_PREFIX = "bytes="


@dataclass(frozen=True)
class ByteRange:
    """A resolved, satisfiable range: absolute offsets into a known-size body."""

    start: int
    end: int  # inclusive, as in the header itself
    total: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def content_range(self) -> str:
        return f"bytes {self.start}-{self.end}/{self.total}"


class UnsatisfiableRange(Exception):
    """The header parsed but asks for bytes that do not exist.

    Distinct from "no header" and from "header we do not understand", because
    RFC 9110 says this one is a 416 carrying `Content-Range: bytes */total`,
    while the other two are an ordinary 200.
    """


def parse_range(header: str | None, total: int) -> ByteRange | None:
    """Resolve a Range header against a body of `total` bytes.

    Returns None when there is no usable range and the caller should send the
    whole body with 200 — that covers a missing header, a unit other than
    bytes, and any syntax we do not accept. Raises `UnsatisfiableRange` only
    for a well-formed range that falls outside the body.

    Suffix ranges (`bytes=-500`, meaning the last 500 bytes) are supported:
    media elements use them to read trailing metadata.
    """
    if not header:
        return None
    header = header.strip()
    if not header.startswith(UNIT_PREFIX):
        return None

    spec = header[len(UNIT_PREFIX) :].strip()
    if "," in spec:  # multi-range: answer 200 with everything instead
        return None
    if "-" not in spec:
        return None

    first, _, last = spec.partition("-")
    first, last = first.strip(), last.strip()

    if total <= 0:
        raise UnsatisfiableRange(spec)

    if not first:
        # Suffix form: the last N bytes. `bytes=-0` asks for nothing.
        if not last.isdigit():
            return None
        suffix = int(last)
        if suffix == 0:
            raise UnsatisfiableRange(spec)
        start = max(0, total - suffix)
        return ByteRange(start=start, end=total - 1, total=total)

    if not first.isdigit():
        return None
    start = int(first)
    if start >= total:
        raise UnsatisfiableRange(spec)

    if not last:
        end = total - 1
    elif last.isdigit():
        # A range that overruns the body is clamped, not rejected: RFC 9110
        # says the last byte is the end of the representation.
        end = min(int(last), total - 1)
    else:
        return None

    if end < start:
        raise UnsatisfiableRange(spec)
    return ByteRange(start=start, end=end, total=total)
