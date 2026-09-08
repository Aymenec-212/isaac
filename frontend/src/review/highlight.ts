/**
 * Rendering a search hit inside a segment (FR-10).
 *
 * The spans come from the server, which is the point: the backend folds accents
 * to decide what matched, and duplicating that folding in TypeScript would mean
 * two implementations that drift and a highlight that lands a character off on
 * every `é`. Here we only slice.
 *
 * Splitting rather than injecting markup, so the caller renders React elements
 * and no transcript text is ever interpolated as HTML.
 */

export interface TextPart {
  text: string;
  match: boolean;
}

type Span = [number, number];

/**
 * Break `text` into alternating plain and matched parts.
 *
 * Defensive about the spans, because they arrive over the wire and a stale
 * response can carry offsets for text that has since changed: anything
 * reversed, out of range, or overlapping a previous span is dropped rather
 * than rendered as a scrambled sentence.
 */
export function splitOnMatches(text: string, spans: readonly Span[] | undefined): TextPart[] {
  if (!spans || spans.length === 0) return [{ text, match: false }];

  const usable = [...spans]
    .filter(
      ([start, end]) =>
        Number.isInteger(start) &&
        Number.isInteger(end) &&
        start >= 0 &&
        end <= text.length &&
        start < end,
    )
    .sort((a, b) => a[0] - b[0]);

  const parts: TextPart[] = [];
  let cursor = 0;
  for (const [start, end] of usable) {
    // A span starting before the cursor overlaps one already emitted; skipping
    // it keeps the concatenation equal to the original text.
    if (start < cursor) continue;
    if (start > cursor) parts.push({ text: text.slice(cursor, start), match: false });
    parts.push({ text: text.slice(start, end), match: true });
    cursor = end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), match: false });

  return parts.length > 0 ? parts : [{ text, match: false }];
}

/** How to describe a filtered transcript, in French. */
export function resultSummary(shown: number, total: number, query: string): string {
  if (!query.trim()) return "";
  if (shown === 0) return `Aucun passage ne contient « ${query.trim()} ».`;
  return `${shown} passage${shown > 1 ? "s" : ""} sur ${total}.`;
}
