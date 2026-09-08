"""Sentencepiece pieces to `WordEvent`s, one step at a time.

The MLX runtime hands back at most one text token per 80 ms step, and a word is
spread across as many steps as it has pieces — 39 of B1's 92 words needed more
than one. Something has to reassemble them, and it has to do so *streaming*,
because the runtime never says "that word is finished".

The rule is the one sentencepiece itself uses: a piece carrying U+2581 starts a
new word, which is also the signal that the previous word is complete. So a
word is emitted when the *next* one begins, or when the stream is flushed.

That costs latency equal to the gap between two words — 80 ms at the median in
B1, 160 ms at the 75th percentile. The alternative, emitting a word before its
pieces have all arrived, would put `budge` in a transcript and then correct it,
which is precisely the retraction X-14 says this pipeline does not do. Paying
one inter-word gap to keep the invariant is the right trade.

Pure: no model import, no I/O, no clock. Timing comes from step indices, which
are frame counts (ADR-11), so it replays identically at any speed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mosaique.speech.interfaces import FRAME_DURATION_MS, WordEvent

WORD_MARKER = "▁"


@dataclass
class PieceAssembler:
    """Fold a stream of sentencepiece pieces into whole words.

    `delay_ms` is the model's own delay — 500 ms for `stt-1b-en_fr`, read from
    `config.json` rather than assumed (B1 §3). A token emitted at step *n*
    describes audio that arrived `delay_ms` earlier, so subtracting it puts the
    word back where it was spoken on the stream timeline.
    """

    delay_ms: int
    pieces: list[str] = field(default_factory=list)
    start_step: int = 0
    last_step: int = 0

    @property
    def has_open_word(self) -> bool:
        return bool(self.pieces)

    def on_piece(self, step: int, piece: str) -> list[WordEvent]:
        """Add one piece. Emits the previous word when this one starts a new."""
        events: list[WordEvent] = []
        if piece.startswith(WORD_MARKER) or not self.pieces:
            events.extend(self.flush())
            self.start_step = step
        self.pieces.append(piece)
        self.last_step = step
        return events

    def flush(self) -> list[WordEvent]:
        """Emit whatever word is open. Called at end of turn and at close."""
        if not self.pieces:
            return []
        text = "".join(self.pieces).replace(WORD_MARKER, "").strip()
        start_step, last_step = self.start_step, self.last_step
        self.pieces = []
        if not text:
            # A piece that is nothing but the word marker. Dropping it keeps
            # empty strings out of the transcript; the step is simply skipped.
            return []
        return [
            WordEvent(
                text=text,
                start_ms=self._to_stream_ms(start_step),
                end_ms=self._to_stream_ms(last_step + 1),
                # The runtime emits no per-word confidence (B1 §4). Inventing
                # one would be worse than admitting there is none.
                confidence=None,
            )
        ]

    def _to_stream_ms(self, step: int) -> int:
        return max(0, step * FRAME_DURATION_MS - self.delay_ms)
