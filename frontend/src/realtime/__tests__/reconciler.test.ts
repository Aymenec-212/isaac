import { describe, expect, it } from "vitest";
import {
  type DeltaMessage,
  type FinalMessage,
  TranscriptReconciler,
} from "../reconciler";

const delta = (seq: number, rev: number, text: string, startMs = 1000, pid = "p1"): DeltaMessage => ({
  type: "transcript.delta",
  participant_id: pid,
  sequence: seq,
  revision: rev,
  text,
  start_ms: startMs,
});

const final = (seq: number, rev: number, text: string, startMs = 1000, pid = "p1"): FinalMessage => ({
  type: "transcript.segment.final",
  participant_id: pid,
  sequence: seq,
  revision: rev,
  segment_id: `seg-${pid}-${seq}`,
  text,
  start_ms: startMs,
  end_ms: startMs + 2000,
});

describe("TranscriptReconciler", () => {
  it("applies a first delta", () => {
    const r = new TranscriptReconciler();
    expect(r.apply(delta(0, 1, "Bonjour"))).toBe(true);
    expect(r.ordered()[0]?.text).toBe("Bonjour");
    expect(r.ordered()[0]?.status).toBe("interim");
  });

  it("applies a higher revision and ignores a lower one", () => {
    const r = new TranscriptReconciler();
    r.apply(delta(0, 2, "Bonjour, je"));
    expect(r.apply(delta(0, 1, "Bonjour"))).toBe(false);
    expect(r.ordered()[0]?.text).toBe("Bonjour, je");
  });

  it("ignores a duplicate revision", () => {
    const r = new TranscriptReconciler();
    r.apply(delta(0, 3, "Bonjour"));
    expect(r.apply(delta(0, 3, "Bonjour"))).toBe(false);
  });

  it("freezes a key once it is final", () => {
    const r = new TranscriptReconciler();
    r.apply(final(0, 4, "Bonjour, je pense."));
    expect(r.apply(delta(0, 99, "something else"))).toBe(false);
    expect(r.ordered()[0]?.text).toBe("Bonjour, je pense.");
    expect(r.ordered()[0]?.status).toBe("final");
  });

  it("keeps participants separate under the same sequence number", () => {
    const r = new TranscriptReconciler();
    r.apply(delta(0, 1, "Amina parle", 1000, "p1"));
    r.apply(delta(0, 1, "Karim parle", 1500, "p2"));
    expect(r.ordered()).toHaveLength(2);
  });

  it("orders across participants by start time, not arrival", () => {
    const r = new TranscriptReconciler();
    r.apply(final(0, 1, "deuxième", 5000, "p2"));
    r.apply(final(0, 1, "premier", 1000, "p1"));
    expect(r.ordered().map((e) => e.text)).toEqual(["premier", "deuxième"]);
  });

  it("is unaffected by out-of-order arrival of a final and its deltas", () => {
    const r = new TranscriptReconciler();
    r.apply(final(0, 5, "Phrase complète."));
    r.apply(delta(0, 3, "Phrase"));
    r.apply(delta(0, 4, "Phrase complète"));
    expect(r.ordered()[0]?.text).toBe("Phrase complète.");
  });

  it("hydrates from the server without losing live finals", () => {
    const r = new TranscriptReconciler();
    r.apply(final(1, 2, "en direct", 3000));
    r.hydrate([final(0, 1, "récupéré", 1000)]);
    expect(r.ordered().map((e) => e.text)).toEqual(["récupéré", "en direct"]);
  });
});
