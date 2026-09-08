/**
 * Review-page playback of stored PCM (FR-11).
 *
 * The server stores headerless 24 kHz s16le mono — exactly the frames the
 * recognizer was given, silence padding included. There is no container, so an
 * `<audio>` element cannot play it; the Web Audio API can, once the samples are
 * converted. That conversion is the interesting part and it lives here as a
 * pure function so it can be tested without a browser.
 *
 * Because the padding is stored too (ADR-11), position is arithmetic rather
 * than a lookup:
 *
 *     byteOffset = sessionMs * BYTES_PER_MS
 *
 * which is what lets a decision cite a segment and the player jump straight to
 * the moment it was said, with no index table on either side.
 */

/** Canonical audio, from tech spec 8.1. Must match `speech/interfaces`. */
export const SAMPLE_RATE_HZ = 24_000;
export const BYTES_PER_SAMPLE = 2;
export const BYTES_PER_MS = (SAMPLE_RATE_HZ * BYTES_PER_SAMPLE) / 1000; // 48

/** Byte offset of a moment in an audio session. */
export function byteOffsetForMs(sessionMs: number): number {
  if (!Number.isFinite(sessionMs) || sessionMs <= 0) return 0;
  // Land on a sample boundary: an odd offset would split an int16 and turn the
  // rest of the buffer into noise.
  const raw = Math.floor(sessionMs * BYTES_PER_MS);
  return raw - (raw % BYTES_PER_SAMPLE);
}

/** How long a stored session runs, from its size alone. */
export function durationMsForBytes(byteLength: number): number {
  return Math.floor(byteLength / BYTES_PER_MS);
}

/**
 * Convert signed 16-bit little-endian PCM into the floats Web Audio wants.
 *
 * Scaling by 32768 rather than 32767 keeps the mapping symmetric: -32768 lands
 * exactly on -1.0, and no sample can exceed the range and clip on the way out.
 */
export function pcmToFloat32(pcm: ArrayBuffer): Float32Array {
  // A trailing odd byte means a truncated sample; drop it rather than reading
  // past the end. Range responses are byte-aligned, not sample-aligned.
  const sampleCount = Math.floor(pcm.byteLength / BYTES_PER_SAMPLE);
  const view = new DataView(pcm);
  const out = new Float32Array(sampleCount);
  for (let i = 0; i < sampleCount; i += 1) {
    out[i] = view.getInt16(i * BYTES_PER_SAMPLE, true) / 32768;
  }
  return out;
}

/** Wrap decoded samples in an AudioBuffer the context can play. */
export function toAudioBuffer(context: BaseAudioContext, samples: Float32Array): AudioBuffer {
  const buffer = context.createBuffer(1, Math.max(samples.length, 1), SAMPLE_RATE_HZ);
  // Write through the channel's own array rather than `copyToChannel`, whose
  // signature pins the backing store to a non-shared ArrayBuffer.
  buffer.getChannelData(0).set(samples);
  return buffer;
}

export type PcmFetcher = (url: string) => Promise<ArrayBuffer>;

/**
 * Plays one participant's stored session, seekable by meeting-relative time.
 *
 * Deliberately small: it holds one decoded buffer and one source node. A
 * meeting's worth of audio at 24 kHz mono is about 170 MB per hour per
 * participant, so this is honest only for prototype-length meetings — Slice 7's
 * object storage is where streaming playback belongs. Recorded rather than
 * hidden, because the review page will feel fine until someone reviews an hour.
 */
export class SessionPlayer {
  private context: AudioContext | null = null;
  private buffer: AudioBuffer | null = null;
  private source: AudioBufferSourceNode | null = null;
  private startedAtContextTime = 0;
  private startedAtOffsetS = 0;
  private playing = false;

  constructor(
    private readonly url: string,
    private readonly fetcher: PcmFetcher,
    /** `epoch_ms` of the session: where it sits on the meeting timeline. */
    private readonly epochMs: number = 0,
  ) {}

  /** Fetch and decode once; later seeks reuse the buffer. */
  async load(context: AudioContext): Promise<void> {
    if (this.buffer) return;
    this.context = context;
    const bytes = await this.fetcher(this.url);
    this.buffer = toAudioBuffer(context, pcmToFloat32(bytes));
  }

  get durationMs(): number {
    return this.buffer ? Math.floor(this.buffer.duration * 1000) : 0;
  }

  /** Where a meeting-relative moment falls inside this session. */
  offsetSecondsFor(meetingMs: number): number {
    const withinSession = Math.max(0, meetingMs - this.epochMs);
    return Math.min(withinSession / 1000, this.buffer?.duration ?? 0);
  }

  /** Play from a meeting-relative moment. Restarts cleanly if already playing. */
  playFrom(meetingMs: number): void {
    if (!this.context || !this.buffer) return;
    this.stop();

    const offset = this.offsetSecondsFor(meetingMs);
    const source = this.context.createBufferSource();
    source.buffer = this.buffer;
    source.connect(this.context.destination);
    source.onended = () => {
      // Only clear if this is still the current source: a seek replaces the
      // node and the old one fires `onended` on its way out.
      if (this.source === source) this.playing = false;
    };
    source.start(0, offset);

    this.source = source;
    this.startedAtContextTime = this.context.currentTime;
    this.startedAtOffsetS = offset;
    this.playing = true;
  }

  stop(): void {
    if (this.source) {
      this.source.onended = null;
      try {
        this.source.stop();
      } catch {
        // Already stopped; a second stop() is not an error worth surfacing.
      }
      this.source = null;
    }
    this.playing = false;
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  /** Current head position, meeting-relative, for a progress indicator. */
  positionMs(): number {
    if (!this.context || !this.playing) {
      return this.epochMs + this.startedAtOffsetS * 1000;
    }
    const elapsed = this.context.currentTime - this.startedAtContextTime;
    return this.epochMs + (this.startedAtOffsetS + elapsed) * 1000;
  }
}
