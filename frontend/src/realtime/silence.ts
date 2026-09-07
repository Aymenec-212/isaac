/**
 * "No audio detected" (tech spec 8.2, failure matrix row 2).
 *
 * A muted hardware switch, a microphone the browser opened but the OS is
 * feeding silence, a headset on the wrong input: all of these look like a
 * working meeting until nobody's words appear. The worklet already reports RMS
 * every 100 ms, so this is the cheapest honest warning available.
 *
 * Pure and clock-injected, so the ten-second wait is testable in a millisecond.
 */
export const SILENCE_FLOOR = 0.001;
export const SILENCE_AFTER_MS = 10_000;

export class SilenceWatcher {
  private quietSince: number | null = null;
  private reported = false;

  constructor(
    private readonly afterMs = SILENCE_AFTER_MS,
    private readonly floor = SILENCE_FLOOR,
  ) {}

  /** Feed one level reading. Returns true the first time silence is confirmed. */
  observe(level: number, nowMs: number): boolean {
    if (level > this.floor) {
      this.quietSince = null;
      this.reported = false;
      return false;
    }
    if (this.quietSince === null) this.quietSince = nowMs;
    if (this.reported || nowMs - this.quietSince < this.afterMs) return false;
    this.reported = true;
    return true;
  }

  get silent(): boolean {
    return this.reported;
  }
}
