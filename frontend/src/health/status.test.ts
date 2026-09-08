import { describe, expect, it } from "vitest";
import type { ReadinessResponse } from "../api/client";
import { bannerFor, diagnosticLines, pollIntervalMs } from "./status";

const dep = (name: string, state: string, gates: boolean) => ({
  name,
  state,
  detail: `${name} is ${state}`,
  gates_readiness: gates,
});

const readiness = (deps: ReturnType<typeof dep>[]): ReadinessResponse =>
  ({
    status: deps.some((d) => d.gates_readiness && d.state !== "ok") ? "not_ready" : "ready",
    version: "0.1.0",
    summary: "",
    dependencies: deps,
  }) as unknown as ReadinessResponse;

describe("what to tell a person", () => {
  it("says nothing when everything works", () => {
    const banner = bannerFor(
      readiness([
        dep("database", "ok", true),
        dep("asr_runtime", "ok", true),
        dep("llm_provider", "ok", false),
      ]),
    );

    expect(banner.severity).toBe("ok");
    expect(banner.message).toBe("");
    expect(banner.canStartMeeting).toBe(true);
  });

  it("blocks the meeting when the database is down", () => {
    const banner = bannerFor(
      readiness([dep("database", "unavailable", true), dep("asr_runtime", "ok", true)]),
    );

    expect(banner.severity).toBe("blocked");
    expect(banner.canStartMeeting).toBe(false);
    expect(banner.message).toContain("base de données");
  });

  it("blocks the meeting when the transcription engine is not ready", () => {
    const banner = bannerFor(readiness([dep("asr_runtime", "unknown", true)]));

    expect(banner.canStartMeeting).toBe(false);
    expect(banner.message).toContain("transcription");
  });

  it("lets the meeting proceed when only the summary provider is down", () => {
    // The behaviour the backend already guarantees: a failing provider leaves
    // the transcript and the meeting untouched. The banner must not contradict
    // it by telling someone they cannot meet.
    const banner = bannerFor(
      readiness([
        dep("database", "ok", true),
        dep("asr_runtime", "ok", true),
        dep("llm_provider", "unavailable", false),
      ]),
    );

    expect(banner.severity).toBe("warning");
    expect(banner.canStartMeeting).toBe(true);
    expect(banner.message).toContain("compte rendu");
    expect(banner.message).toContain("fonctionnent normalement");
  });

  it("leads with what blocks the meeting, not with what delays the summary", () => {
    // Both are broken. Telling someone their summary will be late, while the
    // meeting cannot start at all, would be actively misleading.
    const banner = bannerFor(
      readiness([
        dep("database", "unavailable", true),
        dep("llm_provider", "unavailable", false),
      ]),
    );

    expect(banner.severity).toBe("blocked");
    expect(banner.culprits).toEqual(["database"]);
    expect(banner.message).not.toContain("compte rendu");
  });

  it("names every blocking dependency when more than one is down", () => {
    const banner = bannerFor(
      readiness([dep("database", "unavailable", true), dep("asr_runtime", "unavailable", true)]),
    );

    expect(banner.culprits).toEqual(["database", "asr_runtime"]);
  });

  it("treats an unreachable server as its own case", () => {
    // Distinct from "a dependency is down": nothing answered at all, and the
    // thing to check is different.
    const banner = bannerFor(null);

    expect(banner.severity).toBe("unreachable");
    expect(banner.canStartMeeting).toBe(false);
  });

  it("falls back to naming an unrecognised dependency rather than staying silent", () => {
    // A dependency added on the server before the client knows about it must
    // still surface — silence would be the one unacceptable outcome.
    const banner = bannerFor(readiness([dep("redis", "unavailable", true)]));

    expect(banner.message).toContain("redis");
    expect(banner.canStartMeeting).toBe(false);
  });
});

describe("the technical detail, kept separate", () => {
  it("lists only what is broken, with the server's own wording", () => {
    const lines = diagnosticLines(
      readiness([dep("database", "ok", true), dep("asr_runtime", "not_ready", true)]),
    );

    expect(lines).toHaveLength(1);
    expect(lines[0]).toContain("asr_runtime");
    expect(lines[0]).toContain("not_ready");
  });

  it("has nothing to say when the server never answered", () => {
    expect(diagnosticLines(null)).toEqual([]);
  });
});

describe("polling", () => {
  it("backs off when healthy and hurries when not", () => {
    // Someone who has just restarted the model wants the banner to clear; a
    // working server does not need checking every few seconds.
    expect(pollIntervalMs("ok")).toBeGreaterThan(pollIntervalMs("blocked"));
    expect(pollIntervalMs("unreachable")).toBe(pollIntervalMs("blocked"));
  });
});
