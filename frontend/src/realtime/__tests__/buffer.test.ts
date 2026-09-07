import { describe, expect, it } from "vitest";
import { FrameBuffer } from "../buffer";

const frame = () => new ArrayBuffer(3840);

describe("FrameBuffer", () => {
  it("holds frames in order and hands them back once", () => {
    const buffer = new FrameBuffer();
    buffer.push(1, frame());
    buffer.push(2, frame());

    expect(buffer.drain().map((f) => f.sequence)).toEqual([1, 2]);
    expect(buffer.size).toBe(0);
    expect(buffer.drain()).toEqual([]);
  });

  it("drops the oldest frames rather than growing without bound", () => {
    // 400 ms of capacity is five frames.
    const buffer = new FrameBuffer(400);
    for (let sequence = 0; sequence < 12; sequence++) buffer.push(sequence, frame());

    expect(buffer.size).toBe(5);
    expect(buffer.drain().map((f) => f.sequence)).toEqual([7, 8, 9, 10, 11]);
  });

  it("reports when it has started dropping", () => {
    const buffer = new FrameBuffer(400);
    for (let sequence = 0; sequence < 4; sequence++) buffer.push(sequence, frame());
    expect(buffer.dropped).toBe(false);

    buffer.push(4, frame());
    expect(buffer.dropped).toBe(true);
  });

  it("keeps at least one frame however small the capacity", () => {
    const buffer = new FrameBuffer(0);
    buffer.push(9, frame());
    expect(buffer.size).toBe(1);
  });
});
