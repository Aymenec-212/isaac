"""Range arithmetic and the audio read path (tech spec 6, FR-11).

Seeking is where a review page quietly stops working: a wrong `Content-Range`
does not raise anything, it just leaves the scrub bar inert. So the arithmetic
is a pure function and it is pinned here, offsets included.
"""

from __future__ import annotations

import pytest

from mosaique.app.api.ranges import UnsatisfiableRange, parse_range
from mosaique.speech.audio.store import BYTES_PER_MS, LocalAudioStore, NullAudioStore

TOTAL = 1_000


# --- no usable range: the caller sends the whole body -----------------------


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(None, id="absent"),
        pytest.param("", id="empty"),
        pytest.param("items=0-10", id="unit is not bytes"),
        pytest.param("bytes=0-10, 20-30", id="multi-range"),
        pytest.param("bytes=abc-def", id="not numbers"),
        pytest.param("bytes=", id="no spec"),
        pytest.param("bytes=10", id="no hyphen"),
    ],
)
def test_a_range_we_do_not_honour_falls_back_to_the_whole_body(header):
    """None means 200 with everything — a legal answer to any range."""
    assert parse_range(header, TOTAL) is None


# --- ranges we do honour ----------------------------------------------------


def test_an_open_ended_range_runs_to_the_last_byte():
    """`bytes=0-` is the probe every media element opens with."""
    resolved = parse_range("bytes=0-", TOTAL)

    assert (resolved.start, resolved.end, resolved.length) == (0, 999, 1000)
    assert resolved.content_range == "bytes 0-999/1000"


def test_a_closed_range_is_inclusive_at_both_ends():
    """Off-by-one here truncates every seek by a byte, silently."""
    resolved = parse_range("bytes=100-199", TOTAL)

    assert resolved.length == 100
    assert resolved.content_range == "bytes 100-199/1000"


def test_a_range_running_past_the_end_is_clamped_not_rejected():
    """RFC 9110: the last byte is the end of the representation."""
    resolved = parse_range("bytes=900-99999", TOTAL)

    assert (resolved.start, resolved.end) == (900, 999)
    assert resolved.length == 100


def test_a_suffix_range_reads_from_the_end():
    resolved = parse_range("bytes=-250", TOTAL)

    assert (resolved.start, resolved.end) == (750, 999)


def test_a_suffix_longer_than_the_body_starts_at_zero():
    resolved = parse_range("bytes=-99999", TOTAL)

    assert (resolved.start, resolved.end) == (0, 999)


# --- ranges that are 416 ----------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("bytes=1000-", id="starts at the length"),
        pytest.param("bytes=5000-6000", id="entirely past the end"),
        pytest.param("bytes=-0", id="suffix of zero bytes"),
        pytest.param("bytes=500-100", id="end before start"),
    ],
)
def test_an_unsatisfiable_range_is_distinguished_from_one_we_ignore(header):
    """416 and 200 are different answers, so they are different outcomes here."""
    with pytest.raises(UnsatisfiableRange):
        parse_range(header, TOTAL)


def test_any_range_against_an_empty_body_is_unsatisfiable():
    with pytest.raises(UnsatisfiableRange):
        parse_range("bytes=0-", 0)


# --- the store read path ----------------------------------------------------


def _written(tmp_path, payload: bytes) -> tuple[LocalAudioStore, str]:
    store = LocalAudioStore(tmp_path)
    key = store.object_key("meeting-1", "session-1")
    with store.open_session("meeting-1", "session-1") as handle:
        handle.write(payload)
    return store, key


def test_the_store_reads_back_exactly_what_the_runtime_wrote(tmp_path):
    store, key = _written(tmp_path, bytes(range(256)) * 4)

    assert store.size_bytes(key) == 1024
    assert b"".join(store.read_range(key, 0, 1024)) == bytes(range(256)) * 4


def test_a_read_spanning_several_chunks_is_contiguous(tmp_path):
    """The chunk size is an implementation detail; the bytes must not be."""
    payload = bytes(i % 251 for i in range(200_000))
    store, key = _written(tmp_path, payload)

    assert b"".join(store.read_range(key, 1_000, 150_000)) == payload[1_000:151_000]


def test_a_timestamp_seek_lands_on_the_right_bytes(tmp_path):
    """FR-11's whole premise: `byte_offset = session_ms * BYTES_PER_MS`.

    The file holds silence padding as well as speech (ADR-11), which is what
    makes this arithmetic rather than an index lookup. If padding ever stopped
    being written, this is the test that would notice.
    """
    one_second = bytes(1000 * BYTES_PER_MS)
    marker = b"\xff" * (10 * BYTES_PER_MS)
    store, key = _written(tmp_path, one_second + marker + one_second)

    read = b"".join(store.read_range(key, 1000 * BYTES_PER_MS, 10 * BYTES_PER_MS))

    assert read == marker


def test_a_missing_file_reads_as_absent_rather_than_raising(tmp_path):
    store = LocalAudioStore(tmp_path)

    assert store.size_bytes("meeting-1/never-written.pcm") is None
    assert b"".join(store.read_range("meeting-1/never-written.pcm", 0, 10)) == b""


def test_a_key_escaping_the_root_is_refused(tmp_path):
    """Defence in depth: keys come from the database, not from requests."""
    (tmp_path.parent / "secret.pcm").write_bytes(b"not yours")
    store = LocalAudioStore(tmp_path)

    assert store.size_bytes("../secret.pcm") is None
    assert b"".join(store.read_range("../secret.pcm", 0, 9)) == b""


def test_the_null_store_reports_nothing_rather_than_silence():
    """A replay wrote no bytes; the route must 404, not serve a silent file
    that a reviewer would mistake for a recording of nobody speaking."""
    store = NullAudioStore()

    assert store.size_bytes(store.object_key("m", "s")) is None
    assert b"".join(store.read_range("m/s.pcm", 0, 10)) == b""
