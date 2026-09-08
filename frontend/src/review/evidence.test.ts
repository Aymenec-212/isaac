import { describe, expect, it } from "vitest";
import type { OutputsResponse, TranscriptResponse } from "../api/client";
import {
  formatTimestamp,
  indexTranscript,
  resolveAll,
  resolveEvidence,
  unplayableCitations,
} from "./evidence";

const transcript = {
  meeting_id: "m1",
  transcript_version: 1,
  participants: [
    { id: "p1", display_name: "Amel", joined_at: "", left_at: null },
    { id: "p2", display_name: "Bruno", joined_at: "", left_at: null },
  ],
  audio_sessions: [
    { id: "as1", participant_id: "p1", epoch_ms: 0 },
    // Bruno joined 30 s in, so his file starts 30 s after the meeting did.
    { id: "as2", participant_id: "p2", epoch_ms: 30_000 },
  ],
  segments: [
    {
      id: "s1",
      participant_id: "p1",
      sequence: 0,
      start_ms: 5_000,
      end_ms: 7_000,
      text: "Le budget est validé.",
      status: "final",
      audio_session_id: "as1",
    },
    {
      id: "s2",
      participant_id: "p2",
      sequence: 0,
      start_ms: 45_000,
      end_ms: 47_000,
      text: "La maquette arrive vendredi.",
      status: "final",
      audio_session_id: "as2",
    },
    {
      // A gap segment: real row, no audio behind it (L-20).
      id: "s3",
      participant_id: "p1",
      sequence: 1,
      start_ms: 60_000,
      end_ms: 62_000,
      text: "",
      status: "gap",
      audio_session_id: null,
    },
  ],
} as unknown as TranscriptResponse;

const index = indexTranscript(transcript);

describe("resolving a citation", () => {
  it("finds the segment, the speaker and the moment", () => {
    const target = resolveEvidence("s1", index)!;

    expect(target.speaker).toBe("Amel");
    expect(target.meetingMs).toBe(5_000);
    expect(target.audioSessionId).toBe("as1");
  });

  it("subtracts the session epoch to get the offset inside the file", () => {
    // Bruno's file starts at 30 s, so 45 s of meeting is 15 s of his recording.
    // Getting this wrong seeks to the wrong moment, which looks like a bad
    // transcript rather than a bad offset.
    const target = resolveEvidence("s2", index)!;

    expect(target.meetingMs).toBe(45_000);
    expect(target.sessionMs).toBe(15_000);
  });

  it("shows a citation with no audio rather than dropping it", () => {
    const target = resolveEvidence("s3", index)!;

    expect(target.audioSessionId).toBeNull();
    expect(target.sessionMs).toBeNull();
  });

  it("returns null only when the segment itself is unknown", () => {
    // The server rejects these before they reach us; belt and braces.
    expect(resolveEvidence("does-not-exist", index)).toBeNull();
  });

  it("survives a transcript that has not loaded yet", () => {
    const empty = indexTranscript(null);

    expect(resolveEvidence("s1", empty)).toBeNull();
  });
});

describe("resolving a whole citation list", () => {
  it("orders citations by when they were said, not how the model listed them", () => {
    const targets = resolveAll(["s2", "s1"], index);

    expect(targets.map((t) => t.segmentId)).toEqual(["s1", "s2"]);
  });

  it("skips ids with no segment but keeps the rest", () => {
    const targets = resolveAll(["s1", "ghost", "s2"], index);

    expect(targets.map((t) => t.segmentId)).toEqual(["s1", "s2"]);
  });
});

describe("timestamps", () => {
  it("matches the mm:ss the prompt showed the model", () => {
    expect(formatTimestamp(0)).toBe("00:00");
    expect(formatTimestamp(65_400)).toBe("01:05");
    expect(formatTimestamp(3_600_000)).toBe("60:00");
  });

  it("never renders a negative time", () => {
    expect(formatTimestamp(-1)).toBe("00:00");
  });
});

describe("counting what cannot be played", () => {
  it("counts citations whose audio is missing", () => {
    const outputs = {
      status: "succeeded",
      summary: "",
      key_points: [],
      decisions: [{ text: "Budget validé.", evidence_segment_ids: ["s1", "s3"] }],
      action_items: [{ text: "Maquette.", evidence_segment_ids: ["s2"] }],
    } as unknown as OutputsResponse;

    // s3 is a gap segment; s1 and s2 both have audio.
    expect(unplayableCitations(outputs, index)).toBe(1);
  });

  it("counts nothing when there are no outputs yet", () => {
    expect(unplayableCitations(null, index)).toBe(0);
  });
});
