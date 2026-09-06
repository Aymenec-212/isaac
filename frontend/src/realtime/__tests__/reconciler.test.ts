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

describe("cross-participant display order (Slice 2)", () => {
  it("orders by start time across participants, not by arrival", () => {
    const r = new TranscriptReconciler();
    r.apply(final(0, 1, "Amina d'abord", 600, "amina"));
    r.apply(final(0, 1, "Bruno ensuite", 2200, "bruno"));
    r.apply(final(1, 1, "Amina encore", 3200, "amina"));

    expect(r.ordered().map((e) => e.text)).toEqual([
      "Amina d'abord",
      "Bruno ensuite",
      "Amina encore",
    ]);
  });

  it("breaks a tie on participant id, so hydrate and live agree", () => {
    const a = new TranscriptReconciler();
    a.apply(final(0, 1, "de bruno", 1000, "bruno"));
    a.apply(final(0, 1, "d'amina", 1000, "amina"));

    const b = new TranscriptReconciler();
    b.apply(final(0, 1, "d'amina", 1000, "amina"));
    b.apply(final(0, 1, "de bruno", 1000, "bruno"));

    expect(a.ordered().map((e) => e.text)).toEqual(b.ordered().map((e) => e.text));
  });

  it("keeps each participant's segments under their own key", () => {
    const r = new TranscriptReconciler();
    r.apply(delta(0, 1, "Amina parle", 600, "amina"));
    r.apply(delta(0, 1, "Bruno parle", 600, "bruno"));

    expect(r.ordered()).toHaveLength(2);
    expect(r.ordered().map((e) => e.participantId).sort()).toEqual(["amina", "bruno"]);
  });
});
