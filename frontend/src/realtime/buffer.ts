/**
 * Frames held while the socket is away (tech spec 7.4).
 *
 * A reconnect inside the grace resumes the same stream, so audio captured
 * while offline is still wanted — it continues the sequence and the server
 * accepts it. What it must not do is grow without bound: a tab left
 * disconnected for an hour would otherwise hold half an hour of PCM in memory.
 * The spec's answer is 15 s, and the oldest frames are dropped first, because
 * a gap the segmenter can mark beats a page that runs out of memory.
 */
const FRAME_MS = 80;

export interface BufferedFrame {
  sequence: number;
  pcm: ArrayBuffer;
}

export class FrameBuffer {
  private frames: BufferedFrame[] = [];
  private readonly capacity: number;

  constructor(capacityMs = 15_000) {
    this.capacity = Math.max(1, Math.floor(capacityMs / FRAME_MS));
  }

  push(sequence: number, pcm: ArrayBuffer): void {
    this.frames.push({ sequence, pcm });
    if (this.frames.length > this.capacity) {
      this.frames.splice(0, this.frames.length - this.capacity);
    }
  }

  /** Everything held, oldest first. The buffer is empty afterwards. */
  drain(): BufferedFrame[] {
    const held = this.frames;
    this.frames = [];
    return held;
  }

  get size(): number {
    return this.frames.length;
  }

  get dropped(): boolean {
    return this.frames.length === this.capacity;
  }
}
