import { describe, expect, it } from "vitest";
import { resultSummary, splitOnMatches } from "./highlight";

/** The invariant that matters: rendering must never alter the transcript. */
const rejoins = (text: string, spans: [number, number][]) =>
  splitOnMatches(text, spans)
    .map((p) => p.text)
    .join("");

describe("highlighting a match", () => {
  it("splits into plain and matched parts", () => {
    const parts = splitOnMatches("le budget est validé", [[3, 9]]);

    expect(parts).toEqual([
      { text: "le ", match: false },
      { text: "budget", match: true },
      { text: " est validé", match: false },
    ]);
  });

  it("handles several matches in one segment", () => {
    const parts = splitOnMatches("budget clos, budget ouvert", [
      [0, 6],
      [13, 19],
    ]);

    expect(parts.filter((p) => p.match).map((p) => p.text)).toEqual(["budget", "budget"]);
  });

  it("keeps the accented original when the query had no accent", () => {
    // The server matched `reunion` against `réunion`; the offsets index the
    // real text, so what renders is what was actually said.
    const text = "La réunion commence";

    const parts = splitOnMatches(text, [[3, 10]]);

    expect(parts.find((p) => p.match)?.text).toBe("réunion");
  });

  it("returns the whole text unmarked when there are no spans", () => {
    expect(splitOnMatches("rien", [])).toEqual([{ text: "rien", match: false }]);
    expect(splitOnMatches("rien", undefined)).toEqual([{ text: "rien", match: false }]);
  });

  it("handles a match at the very start and the very end", () => {
    expect(splitOnMatches("abc", [[0, 3]])).toEqual([{ text: "abc", match: true }]);
    expect(splitOnMatches("xabc", [[1, 4]])).toEqual([
      { text: "x", match: false },
      { text: "abc", match: true },
    ]);
  });
});

describe("spans that arrived wrong", () => {
  // These come over the wire, and a stale response can carry offsets for text
  // that has since changed. Rendering a scrambled sentence would be worse than
  // rendering an unhighlighted one.

  it("never changes the text, whatever the spans say", () => {
    const text = "le budget est validé";

    expect(rejoins(text, [[3, 9]])).toBe(text);
    expect(rejoins(text, [[9, 3]])).toBe(text); // reversed
    expect(rejoins(text, [[0, 500]])).toBe(text); // past the end
    expect(rejoins(text, [[-2, 4]])).toBe(text); // negative
    expect(
      rejoins(text, [
        [3, 9],
        [5, 12],
      ]),
    ).toBe(text); // overlapping
  });

  it("still highlights the valid spans when one is bad", () => {
    const parts = splitOnMatches("budget clos, budget ouvert", [
      [0, 6],
      [900, 999],
    ]);

    expect(parts.filter((p) => p.match).map((p) => p.text)).toEqual(["budget"]);
  });

  it("sorts spans that arrive out of order", () => {
    const parts = splitOnMatches("aa bb aa", [
      [6, 8],
      [0, 2],
    ]);

    expect(parts.map((p) => p.text).join("")).toBe("aa bb aa");
    expect(parts.filter((p) => p.match)).toHaveLength(2);
  });
});

describe("telling a person what they are looking at", () => {
  it("says nothing when nothing is being searched", () => {
    expect(resultSummary(30, 30, "")).toBe("");
    expect(resultSummary(30, 30, "   ")).toBe("");
  });

  it("says how many of how many, so the rest does not look lost", () => {
    expect(resultSummary(3, 30, "budget")).toBe("3 passages sur 30.");
  });

  it("uses the singular for one result", () => {
    expect(resultSummary(1, 30, "budget")).toBe("1 passage sur 30.");
  });

  it("names the query back when nothing matched", () => {
    // Someone who mistyped needs to see what was actually searched for.
    expect(resultSummary(0, 30, "cryptomonnaie")).toContain("cryptomonnaie");
  });
});
