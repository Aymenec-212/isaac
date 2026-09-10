import { describe, expect, it } from "vitest";
import type { TranscriptResponse } from "../api/client";
import {
  PARAGRAPH_SILENCE_MS,
  groupIntoParagraphs,
  paragraphText,
} from "./paragraphs";

type Segment = TranscriptResponse["segments"][number];

let counter = 0;
const seg = (
  participantId: string,
  startMs: number,
  endMs: number,
  text = "mot",
): Segment =>
  ({
    id: `seg${++counter}`,
    participant_id: participantId,
    sequence: counter,
    start_ms: startMs,
    end_ms: endMs,
    text,
    status: "final",
    audio_session_id: "aud1",
  }) as unknown as Segment;

describe("grouping segments into paragraphs", () => {
  it("joins consecutive segments from one speaker separated by short pauses", () => {
    const paragraphs = groupIntoParagraphs([
      seg("p1", 0, 1_000, "Alors bonjour,"),
      seg("p1", 1_400, 2_500, "je m'appelle Ayman."),
      seg("p1", 3_000, 4_000, "J'ai grandi à Casablanca."),
    ]);

    expect(paragraphs).toHaveLength(1);
    expect(paragraphs[0]!.segments).toHaveLength(3);
    expect(paragraphs[0]!.startMs).toBe(0);
    expect(paragraphs[0]!.endMs).toBe(4_000);
  });

  it("starts a new paragraph when the speaker changes, however short the gap", () => {
    // Two people talking over each other is still two paragraphs. Merging on
    // time alone would attribute one person's words to another, which is worse
    // than any formatting problem this module exists to solve.
    const paragraphs = groupIntoParagraphs([
      seg("p1", 0, 1_000),
      seg("p2", 1_010, 2_000),
    ]);

    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]!.participantId).toBe("p1");
    expect(paragraphs[1]!.participantId).toBe("p2");
  });

  it("starts a new paragraph after a long silence from the same speaker", () => {
    const paragraphs = groupIntoParagraphs([
      seg("p1", 0, 1_000),
      seg("p1", 1_000 + PARAGRAPH_SILENCE_MS, 2_000 + PARAGRAPH_SILENCE_MS),
    ]);

    expect(paragraphs).toHaveLength(2);
  });

  it("measures the gap from the previous segment's end, not its start", () => {
    // A long segment followed immediately by another is one continuous thought.
    // Comparing starts would call a 30 s sentence a paragraph break.
    const paragraphs = groupIntoParagraphs([
      seg("p1", 0, 30_000),
      seg("p1", 30_200, 31_000),
    ]);

    expect(paragraphs).toHaveLength(1);
  });

  it("keeps segments separate inside a paragraph", () => {
    // The property FR-10 and FR-11 depend on. If this ever became a joined
    // string, citation scroll targets and highlight offsets would both break,
    // silently and only in the browser.
    const segments = [seg("p1", 0, 1_000, "budget"), seg("p1", 1_200, 2_000, "validé")];
    const [paragraph] = groupIntoParagraphs(segments);

    expect(paragraph!.segments.map((s) => s.id)).toEqual(segments.map((s) => s.id));
    expect(paragraph!.segments.map((s) => s.text)).toEqual(["budget", "validé"]);
  });

  it("re-joins L-28's orphaned final words visually without touching them", () => {
    // The real fixture orphans a sentence's last word into its own 160-400 ms
    // segment, 8 times in 30. Those gaps are far below the paragraph threshold,
    // so a reader stops seeing them. The segments are unchanged and still
    // individually addressable — this hides the defect, it does not fix it.
    const orphan = seg("p1", 2_400, 2_560, "vendredi.");
    const paragraphs = groupIntoParagraphs([
      seg("p1", 0, 2_200, "La maquette est attendue avant"),
      orphan,
    ]);

    expect(paragraphs).toHaveLength(1);
    expect(paragraphs[0]!.segments).toContain(orphan);
    expect(orphan.text).toBe("vendredi.");
  });

  it("handles an empty transcript", () => {
    expect(groupIntoParagraphs([])).toEqual([]);
  });

  it("does not let a paragraph end before something inside it did", () => {
    // Defensive: overlapping ends would otherwise make endMs go backwards and
    // the paragraph's timestamp range a lie.
    const paragraphs = groupIntoParagraphs([
      seg("p1", 0, 5_000),
      seg("p1", 1_000, 2_000),
    ]);

    expect(paragraphs).toHaveLength(1);
    expect(paragraphs[0]!.endMs).toBe(5_000);
  });

  it("collapses a realistic hour into far fewer blocks than segments", () => {
    // The reason the slice exists, as an assertion rather than a claim. An hour
    // of one speaker at the segmenter's real cadence is ~930 segments; a reader
    // should get paragraphs, not 930 labelled lines.
    const segments: Segment[] = [];
    let t = 0;
    for (let i = 0; i < 930; i++) {
      segments.push(seg("p1", t, t + 2_500));
      // Mostly within-thought gaps, with a real pause every twelfth segment.
      t += 2_500 + (i % 12 === 11 ? 6_000 : 900);
    }

    const paragraphs = groupIntoParagraphs(segments);

    expect(segments).toHaveLength(930);
    expect(paragraphs.length).toBeLessThan(100);
    // Nothing is lost on the way: every segment appears exactly once.
    const grouped = paragraphs.flatMap((p) => p.segments);
    expect(grouped).toHaveLength(930);
    expect(new Set(grouped.map((s) => s.id)).size).toBe(930);
  });

  it("preserves timeline order across paragraphs", () => {
    const paragraphs = groupIntoParagraphs([
      seg("p1", 0, 1_000),
      seg("p2", 10_000, 11_000),
      seg("p1", 20_000, 21_000),
    ]);

    expect(paragraphs.map((p) => p.startMs)).toEqual([0, 10_000, 20_000]);
  });
});

describe("paragraphText", () => {
  it("joins the segment texts with single spaces", () => {
    const [paragraph] = groupIntoParagraphs([
      seg("p1", 0, 1_000, "Le budget"),
      seg("p1", 1_200, 2_000, "est validé."),
    ]);

    expect(paragraphText(paragraph!)).toBe("Le budget est validé.");
  });

  it("drops empty segments rather than emitting double spaces", () => {
    const [paragraph] = groupIntoParagraphs([
      seg("p1", 0, 1_000, "Le budget"),
      seg("p1", 1_100, 1_200, "   "),
      seg("p1", 1_300, 2_000, "est validé."),
    ]);

    expect(paragraphText(paragraph!)).toBe("Le budget est validé.");
  });
});
