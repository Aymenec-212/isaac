"""Transcript search (FR-10), and the French-language reason it is not ILIKE.

The property that matters most here is the boring one: offsets returned by the
server must slice the *original* text correctly. A highlight that drifts by one
character on every accent would be worse than no highlight, because it looks
deliberate.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mosaique.transcript.search import find_spans, fold, search


@dataclass(frozen=True)
class Seg:
    id: str
    text: str


TRANSCRIPT = [
    Seg("s1", "Bonjour à tous."),
    Seg("s2", "La réunion de budget commence."),
    Seg("s3", "Le BUDGET du trimestre est validé."),
    Seg("s4", "Rien à voir avec le sujet."),
    Seg("s5", "Réunion terminée, budget clos, budget approuvé."),
]


# --- folding ---------------------------------------------------------------


def test_folding_preserves_length_exactly():
    """The invariant every returned offset depends on.

    NFD would split `é` into two code points and slide every later offset; the
    folding here is per character precisely so index i maps to index i.
    """
    for text in ["réunion", "ÉÀÜÇ", "Bonjour à tous.", "straße", "", "no accents"]:
        assert len(fold(text)) == len(text), f"length changed folding {text!r}"


def test_folding_removes_accents_and_case():
    assert fold("Réunion") == "reunion"
    assert fold("ÉLÈVE") == "eleve"
    assert fold("Ça") == "ca"


# --- the French case the spec's ILIKE would have failed --------------------


def test_an_unaccented_query_finds_accented_text():
    """The whole reason this is not ILIKE.

    People type `reunion`. The transcript says `réunion`. ILIKE returns nothing
    and the user concludes the search is broken.
    """
    matched, _ = search(TRANSCRIPT, "reunion")

    assert [s.id for s in matched] == ["s2", "s5"]


def test_an_accented_query_finds_unaccented_text_too():
    """Symmetry, so neither side has to guess how the other typed it."""
    matched, _ = search([Seg("s1", "reunion de budget")], "réunion")

    assert [s.id for s in matched] == ["s1"]


def test_search_ignores_case():
    matched, _ = search(TRANSCRIPT, "budget")

    assert [s.id for s in matched] == ["s2", "s3", "s5"]


# --- offsets ---------------------------------------------------------------


def test_spans_slice_the_original_text_not_the_folded_one():
    """The assertion that catches an off-by-one introduced by accents.

    `réunion` sits after an accented character in this sentence, so a folding
    that changed length would produce a span pointing at the wrong substring —
    and the test would still pass if it only checked that *a* span was found.
    """
    text = "La réunion de budget a été décalée."

    spans = find_spans(text, "budget")

    assert len(spans) == 1
    start, end = spans[0]
    assert text[start:end] == "budget"


def test_every_occurrence_is_returned_not_just_the_first():
    text = "budget clos, budget approuvé"

    spans = find_spans(text, "budget")

    assert len(spans) == 2
    assert [text[a:b] for a, b in spans] == ["budget", "budget"]


def test_spans_do_not_overlap():
    """`aa` in `aaaa` is two matches, not three."""
    spans = find_spans("aaaa", "aa")

    assert spans == ((0, 2), (2, 4))


def test_an_accented_match_slices_back_with_its_accent_intact():
    text = "La réunion commence."

    spans = find_spans(text, "reunion")

    start, end = spans[0]
    assert text[start:end] == "réunion", "the original spelling must survive the round trip"


def test_matches_are_keyed_by_segment_and_carry_their_spans():
    _, matches = search(TRANSCRIPT, "budget")

    assert set(matches) == {"s2", "s3", "s5"}
    assert len(matches["s5"].spans) == 2, "two occurrences in one segment"


# --- queries that should not filter ---------------------------------------


@pytest.mark.parametrize("query", ["", "   ", "a", " b "])
def test_a_blank_or_too_short_query_returns_the_whole_transcript(query):
    """Clearing the box gives you your transcript back, not an empty page.

    One character would match most of a transcript anyway, so filtering on it
    is worse than not filtering.
    """
    matched, matches = search(TRANSCRIPT, query)

    assert len(matched) == len(TRANSCRIPT)
    assert matches == {}


def test_surrounding_whitespace_is_ignored():
    matched, _ = search(TRANSCRIPT, "  budget  ")

    assert [s.id for s in matched] == ["s2", "s3", "s5"]


def test_a_query_matching_nothing_returns_nothing():
    matched, matches = search(TRANSCRIPT, "cryptomonnaie")

    assert matched == []
    assert matches == {}


# --- ordering --------------------------------------------------------------


def test_results_keep_transcript_order():
    """A filtered transcript, not a relevance ranking.

    The caller already sorted for display; results that jump around are harder
    to read than the same conversation with the gaps removed.
    """
    scrambled = [TRANSCRIPT[4], TRANSCRIPT[1], TRANSCRIPT[2]]

    matched, _ = search(scrambled, "budget")

    assert [s.id for s in matched] == ["s5", "s2", "s3"], "input order is preserved as given"


def test_searching_an_empty_transcript_is_not_an_error():
    matched, matches = search([], "budget")

    assert matched == []
    assert matches == {}
