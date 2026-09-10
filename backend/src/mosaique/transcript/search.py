"""Text search within a meeting's transcript (FR-10, tech spec §6 `?q=`).

**Deviation from the spec, recorded rather than smuggled.** §6 says "ILIKE for
now". This does the matching in Python instead, and the reason is the product:
Mosaïque is French-first, and `ILIKE` in PostgreSQL is accent-sensitive. A person
who types `reunion` would find nothing in a transcript that says `réunion`, and
typing accents is exactly what people skip. Getting that wrong is a trust
failure in a feature whose whole job is finding what was said.

The alternative — `CREATE EXTENSION unaccent` — needs privileges that a local
`docker compose` or a hosted database may not grant, which is a poor trade during
a phase whose point is that the local path works reliably.

What this costs: the search is meeting-scoped and linear. That is affordable
because it always was — `list_for_meeting` already loads every segment to render
the transcript, so `?q=` adds a filter, not a fetch. An hour of French is about
930 segments. Cross-meeting search would need PostgreSQL full-text and is not
FR-10 (L-33).

Returns match offsets rather than leaving the client to find them again: the
highlight then cannot disagree with what the server actually matched.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

# A query shorter than this matches most of a transcript and helps nobody.
MIN_QUERY_LENGTH = 2


class SearchableSegment(Protocol):
    id: str
    text: str


@dataclass(frozen=True)
class SegmentMatch:
    """One segment that matched, and where."""

    segment_id: str
    # Half-open [start, end) offsets into the segment's **original** text, so a
    # client can slice it directly. Folding never changes length — see `fold`.
    spans: tuple[tuple[int, int], ...]


def fold(text: str) -> str:
    """Casefold and strip accents, preserving length character for character.

    Length preservation is the property the offsets depend on. NFD splits `é`
    into `e` + a combining accent, so dropping the combining marks would shorten
    the string and slide every later offset. Instead each original character is
    folded on its own and, if it collapses to nothing or to several characters,
    replaced by a single placeholder — so index *i* of the result always
    corresponds to index *i* of the input.

    `casefold` rather than `lower`, because it handles the cases `lower` does
    not — German `ß`, and Turkish dotted/dotless `i`, both of which can appear
    in a French meeting through a name.
    """
    out: list[str] = []
    for char in text:
        decomposed = unicodedata.normalize("NFD", char)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        folded = stripped.casefold()
        # One character in, one character out. A character that folds to several
        # (or to none) keeps its original so the mapping stays exact; it simply
        # will not match an accent-folded query, which is the honest outcome.
        out.append(folded if len(folded) == 1 else char.casefold()[:1] or char)
    return "".join(out)


def find_spans(text: str, query: str) -> tuple[tuple[int, int], ...]:
    """Every non-overlapping occurrence of `query` in `text`, accent-insensitively."""
    folded_text = fold(text)
    folded_query = fold(query)
    if not folded_query:
        return ()

    spans: list[tuple[int, int]] = []
    start = folded_text.find(folded_query)
    while start != -1:
        end = start + len(folded_query)
        spans.append((start, end))
        start = folded_text.find(folded_query, end)
    return tuple(spans)


def search[SegmentT: SearchableSegment](
    segments: Sequence[SegmentT], query: str
) -> tuple[list[SegmentT], dict[str, SegmentMatch]]:
    """Filter a transcript to the segments containing `query`.

    Order is preserved: the caller has already sorted for display, and search
    results that jump around are harder to read than a filtered transcript.

    A blank or too-short query returns everything unfiltered rather than nothing.
    Someone clearing the box wants their transcript back, not an empty page.

    Generic in the segment type, so the caller gets back exactly what it passed
    in. That matters since Slice 6R item 7: the route searches the *presented*
    segments, whose `text` already has any correction applied, rather than the
    database rows. Search a corrected transcript against its raw text and the
    spans returned index into a string the reader cannot see — the highlight
    lands on the wrong words, and only in the browser.
    """
    stripped = query.strip()
    if len(stripped) < MIN_QUERY_LENGTH:
        return list(segments), {}

    matched: list[SegmentT] = []
    matches: dict[str, SegmentMatch] = {}
    for segment in segments:
        spans = find_spans(segment.text, stripped)
        if spans:
            matched.append(segment)
            matches[segment.id] = SegmentMatch(segment_id=segment.id, spans=spans)
    return matched, matches
