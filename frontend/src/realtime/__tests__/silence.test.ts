import { describe, expect, it } from "vitest";
import { SilenceWatcher } from "../silence";

describe("SilenceWatcher", () => {
  it("says nothing until the silence has lasted long enough", () => {
    const watcher = new SilenceWatcher(10_000);
    expect(watcher.observe(0, 0)).toBe(false);
    expect(watcher.observe(0, 9_999)).toBe(false);
    expect(watcher.observe(0, 10_000)).toBe(true);
    expect(watcher.silent).toBe(true);
  });

  it("reports once, not on every reading afterwards", () => {
    const watcher = new SilenceWatcher(1_000);
    watcher.observe(0, 0);
    expect(watcher.observe(0, 1_000)).toBe(true);
    expect(watcher.observe(0, 1_100)).toBe(false);
    expect(watcher.observe(0, 5_000)).toBe(false);
  });

  it("a single sound restarts the clock", () => {
    const watcher = new SilenceWatcher(1_000);
    watcher.observe(0, 0);
    watcher.observe(0.5, 900);
    // The window restarts at the first quiet reading after the sound, at 1500.
    expect(watcher.observe(0, 1_500)).toBe(false);
    expect(watcher.observe(0, 2_499)).toBe(false);
    expect(watcher.observe(0, 2_500)).toBe(true);
  });

  it("treats near-zero as silence, since a real microphone is never exactly 0", () => {
    const watcher = new SilenceWatcher(100);
    watcher.observe(0.0001, 0);
    expect(watcher.observe(0.0001, 100)).toBe(true);
  });

  it("clears once sound comes back, so the banner can go away", () => {
    const watcher = new SilenceWatcher(100);
    watcher.observe(0, 0);
    expect(watcher.observe(0, 100)).toBe(true);
    watcher.observe(0.9, 200);
    expect(watcher.silent).toBe(false);
  });
});
