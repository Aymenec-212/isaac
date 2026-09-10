/**
 * Grouping final segments into something a person can read (Slice 6R, items 1 and 3).
 *
 * **The problem this solves is a measured one.** The segmenter closes a segment
 * after 1 200 ms of silence (§9.3), so an hour of French is roughly 930 segments.
 * Rendered one paragraph each with the speaker's name repeated on every line,
 * that is a log of model events, not a transcript. Slice 6R's principle: keep the
 * raw segment and word evidence internally, present something readable by
 * default.
 *
 * **The constraint that shapes the whole module.** Two features already work and
 * are keyed to individual segments: a citation scrolls to a segment id (FR-11),
 * and a search highlight indexes into *one segment's* text at server-returned
 * offsets (FR-10). Joining segment texts into one string would break both — the
 * offsets would be wrong by however much preceded them in the paragraph, and
 * there would be nothing left to scroll to.
 *
 * So a paragraph here is **a list of segments, not a concatenated string**. The
 * renderer keeps one element per segment inside the paragraph; grouping changes
 * how it looks, never what is addressable. Everything downstream that knew about
 * segments still does.
 *
 * **What this does not do.** It does not fix L-28. Eight of thirty segments in
 * the real fixture are a sentence's final word alone in a 160-400 ms segment;
 * those gaps are far below any paragraph threshold, so grouping re-joins them
 * visually. The defect is unchanged — the raw segments are exactly as the model
 * produced them, `test_l28_orphaned_final_word.py` still pins its shape, and a
 * reader who opens the raw view still sees it. Hiding a defect is not fixing one.
 */

import type { TranscriptResponse } from "../api/client";

type Segment = TranscriptResponse["segments"][number];

/**
 * A silence longer than this starts a new paragraph, in ms. **[measure]**
 *
 * A guess, and flagged as one. It has to be comfortably above the segmenter's
 * own 1 200 ms silence rule — otherwise every segment boundary would also be a
 * paragraph boundary and the grouping would do nothing — and below the length of
 * a real pause between topics. 3 500 ms is that, chosen by reasoning rather than
 * measured, and it has **not** been tuned against the fake recognizer, which
 * would be tuning against a metronome (CLAUDE.md).
 *
 * How to measure it properly: read the gap distribution off a real MLX run's
 * segments and pick a threshold that separates within-thought pauses from
 * between-thought ones, the way §9.3 was retuned from Spike B1's word timings.
 */
export const PARAGRAPH_SILENCE_MS = 3_500;

/**
 * A paragraph is a run of one speaker's segments, unbroken by a long pause.
 *
 * `segments` is the point: they stay separate so a citation can still find one
 * and a highlight can still be applied to one.
 */
export interface Paragraph {
  /** Stable across renders: the first segment's id. */
  key: string;
  participantId: string;
  /** Meeting-relative, for the timestamp shown beside the speaker. */
  startMs: number;
  endMs: number;
  segments: Segment[];
}

/**
 * Group ordered final segments by speaker and by pause.
 *
 * A new paragraph starts when the speaker changes, or when the gap since the
 * previous segment ended is at least `silenceMs`. Segments are assumed to arrive
 * in timeline order — `GET /transcript` returns them that way and the
 * lifecycle test asserts it — so this does not re-sort and cannot silently
 * reorder someone's words.
 */
export function groupIntoParagraphs(
  segments: readonly Segment[],
  silenceMs: number = PARAGRAPH_SILENCE_MS,
): Paragraph[] {
  const paragraphs: Paragraph[] = [];

  for (const segment of segments) {
    const current = paragraphs[paragraphs.length - 1];
    const sameSpeaker = current?.participantId === segment.participant_id;
    // `endMs` is the previous segment's end, so this is the real silence
    // between them rather than a distance between two starts.
    const gap = current ? segment.start_ms - current.endMs : Infinity;

    if (current && sameSpeaker && gap < silenceMs) {
      current.segments.push(segment);
      // Guard against a non-monotonic end: a paragraph must never claim to end
      // before something inside it did.
      current.endMs = Math.max(current.endMs, segment.end_ms);
      continue;
    }

    paragraphs.push({
      key: segment.id,
      participantId: segment.participant_id,
      startMs: segment.start_ms,
      endMs: segment.end_ms,
      segments: [segment],
    });
  }

  return paragraphs;
}

/**
 * Join one paragraph's segment texts for display.
 *
 * Only for places that genuinely need a single string — a copy button, an aria
 * label. **Not** for rendering: rendering goes segment by segment so highlight
 * offsets and citation targets survive. Kept here so the separator is defined
 * once rather than guessed at each call site.
 */
export function paragraphText(paragraph: Paragraph): string {
  return paragraph.segments
    .map((segment) => segment.text.trim())
    .filter(Boolean)
    .join(" ");
}
