import { describe, expect, it } from "vitest";
import {
  isRosterMessage,
  ParticipantRoster,
  type ParticipantMessage,
  type SpeakingMessage,
} from "../roster";

const joined = (pid: string, name: string): ParticipantMessage => ({
  type: "participant.joined",
  participant_id: pid,
  display_name: name,
});

const left = (pid: string, name: string): ParticipantMessage => ({
  type: "participant.left",
  participant_id: pid,
  display_name: name,
});

const speaking = (pid: string, on: boolean): SpeakingMessage => ({
  type: "participant.speaking",
  participant_id: pid,
  active: on,
});

describe("ParticipantRoster", () => {
  it("lists participants in join order", () => {
    const r = new ParticipantRoster();
    r.apply(joined("p1", "Amina"));
    r.apply(joined("p2", "Bruno"));
    expect(r.ordered().map((e) => e.displayName)).toEqual(["Amina", "Bruno"]);
  });

  it("ignores a replayed join, so a late joiner sees the room once", () => {
    const r = new ParticipantRoster();
    expect(r.apply(joined("p1", "Amina"))).toBe(true);
    expect(r.apply(joined("p1", "Amina"))).toBe(false);
    expect(r.ordered()).toHaveLength(1);
  });

  it("marks a speaker and then quiets them", () => {
    const r = new ParticipantRoster();
    r.apply(joined("p1", "Amina"));
    expect(r.apply(speaking("p1", true))).toBe(true);
    expect(r.ordered()[0]?.speaking).toBe(true);
    expect(r.apply(speaking("p1", true))).toBe(false);
    expect(r.apply(speaking("p1", false))).toBe(true);
    expect(r.ordered()[0]?.speaking).toBe(false);
  });

  it("drops speaking for someone it has never been told about", () => {
    const r = new ParticipantRoster();
    expect(r.apply(speaking("ghost", true))).toBe(false);
    expect(r.ordered()).toHaveLength(0);
  });

  it("keeps a departed participant, named, and no longer speaking", () => {
    const r = new ParticipantRoster();
    r.apply(joined("p2", "Bruno"));
    r.apply(speaking("p2", true));
    r.apply(left("p2", "Bruno"));

    const [entry] = r.ordered();
    expect(entry?.present).toBe(false);
    expect(entry?.speaking).toBe(false);
    // Their segments are still in the transcript and still need a name.
    expect(r.nameFor("p2")).toBe("Bruno");
  });

  it("falls back to a neutral name for an unknown speaker", () => {
    expect(new ParticipantRoster().nameFor("p9")).toBe("Participant");
  });

  it("recognises only roster messages", () => {
    expect(isRosterMessage({ type: "participant.speaking" })).toBe(true);
    expect(isRosterMessage({ type: "transcript.delta" })).toBe(false);
  });
});
