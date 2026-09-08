import { describe, expect, it } from "vitest";
import {
  BYTES_PER_MS,
  byteOffsetForMs,
  durationMsForBytes,
  pcmToFloat32,
} from "./playback";

/**
 * The arithmetic FR-11 rests on. A wrong offset here does not throw — it plays
 * the wrong moment, which is indistinguishable from a bad transcript to anyone
 * checking a decision against the recording.
 */
describe("timeline arithmetic", () => {
  it("matches the canonical format the server stores", () => {
    // 24 kHz x 2 bytes / 1000 ms. If this changes, the server changed too.
    expect(BYTES_PER_MS).toBe(48);
  });

  it("converts a moment into a byte offset", () => {
    expect(byteOffsetForMs(0)).toBe(0);
    expect(byteOffsetForMs(1000)).toBe(48_000);
    expect(byteOffsetForMs(65_400)).toBe(65_400 * 48);
  });

  it("always lands on a sample boundary", () => {
    // An odd offset splits an int16 and turns everything after it into noise.
    for (const ms of [1, 7, 13.5, 999.9]) {
      expect(byteOffsetForMs(ms) % 2).toBe(0);
    }
  });

  it("treats nonsense positions as the start rather than seeking backwards", () => {
    expect(byteOffsetForMs(-500)).toBe(0);
    expect(byteOffsetForMs(Number.NaN)).toBe(0);
  });

  it("reads a duration back out of a file size", () => {
    expect(durationMsForBytes(48_000)).toBe(1000);
    expect(durationMsForBytes(0)).toBe(0);
  });

  it("round-trips a position through offset and duration", () => {
    expect(durationMsForBytes(byteOffsetForMs(12_345))).toBe(12_345);
  });
});

describe("pcm decoding", () => {
  const encode = (samples: number[]): ArrayBuffer => {
    const buffer = new ArrayBuffer(samples.length * 2);
    const view = new DataView(buffer);
    samples.forEach((value, i) => view.setInt16(i * 2, value, true));
    return buffer;
  };

  it("reads little-endian signed 16-bit samples", () => {
    const decoded = pcmToFloat32(encode([0, 16384, -16384]));

    expect(decoded.length).toBe(3);
    expect(decoded[0]).toBe(0);
    expect(decoded[1]).toBeCloseTo(0.5, 5);
    expect(decoded[2]).toBeCloseTo(-0.5, 5);
  });

  it("maps the extremes inside [-1, 1] without clipping", () => {
    // Scaling by 32768 keeps this symmetric; 32767 would push -32768 past -1.
    const decoded = pcmToFloat32(encode([32767, -32768]));

    expect(decoded[0]).toBeLessThan(1);
    expect(decoded[1]).toBe(-1);
  });

  it("ignores a trailing half sample instead of reading past the end", () => {
    // Range responses are byte-aligned, so an odd length is reachable.
    const odd = new Uint8Array([0x00, 0x40, 0x7f]).buffer;

    const decoded = pcmToFloat32(odd);

    expect(decoded.length).toBe(1);
    expect(decoded[0]).toBeCloseTo(0.5, 5);
  });

  it("decodes silence as silence", () => {
    const decoded = pcmToFloat32(new ArrayBuffer(48 * 2));

    expect(decoded.length).toBe(48);
    expect(decoded.every((v) => v === 0)).toBe(true);
  });

  it("handles an empty body", () => {
    expect(pcmToFloat32(new ArrayBuffer(0)).length).toBe(0);
  });
});
