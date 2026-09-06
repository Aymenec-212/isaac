/**
 * Capture worklet: device rate (usually 48 kHz float) -> 24 kHz s16le mono,
 * emitted as 80 ms frames (1920 samples, 3840 bytes).
 *
 * Resampling happens here rather than on the server so the wire format is
 * already the model's native format (tech spec 8.1, 8.2). That keeps bandwidth
 * at ~48 KB/s per participant and means the backend never guesses a rate.
 *
 * Runs on the audio thread, so it must stay cheap: a linear-interpolation
 * resampler and one Int16 conversion, nothing allocated per render quantum
 * beyond the outgoing frame.
 */
const TARGET_RATE = 24000;
const FRAME_SAMPLES = 1920; // 80 ms at 24 kHz
const LEVEL_INTERVAL_FRAMES = 12; // ~100 ms between level reports

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ratio = sampleRate / TARGET_RATE;
    this._buffer = new Float32Array(FRAME_SAMPLES);
    this._filled = 0;
    this._position = 0;
    this._carry = new Float32Array(0);
    this._framesSinceLevel = 0;
    this._peak = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    // Keep one sample of history so interpolation is continuous across quanta.
    const source = new Float32Array(this._carry.length + channel.length);
    source.set(this._carry, 0);
    source.set(channel, this._carry.length);

    let cursor = this._position;
    while (cursor + 1 < source.length) {
      const index = Math.floor(cursor);
      const fraction = cursor - index;
      const sample = source[index] * (1 - fraction) + source[index + 1] * fraction;

      this._buffer[this._filled++] = sample;
      const magnitude = sample < 0 ? -sample : sample;
      if (magnitude > this._peak) this._peak = magnitude;

      if (this._filled === FRAME_SAMPLES) {
        const pcm = new Int16Array(FRAME_SAMPLES);
        for (let i = 0; i < FRAME_SAMPLES; i++) {
          const clamped = Math.max(-1, Math.min(1, this._buffer[i]));
          pcm[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
        }
        this.port.postMessage({ type: "frame", pcm: pcm.buffer }, [pcm.buffer]);
        this._filled = 0;

        if (++this._framesSinceLevel >= LEVEL_INTERVAL_FRAMES) {
          this.port.postMessage({ type: "level", value: this._peak });
          this._framesSinceLevel = 0;
          this._peak = 0;
        }
      }
      cursor += this._ratio;
    }

    const consumed = Math.floor(cursor);
    this._carry = source.slice(Math.max(0, consumed - 1));
    this._position = cursor - consumed + (consumed > 0 ? 1 : 0);
    return true;
  }
}

registerProcessor("mosaique-capture", CaptureProcessor);
