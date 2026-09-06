/**
 * Binary frame encoder, the mirror of `realtime/protocol/frames.py`.
 * [u8 version=1][u32 seq][u32 capture_ms][s16le PCM x 1920] = 3849 bytes.
 */
export const FRAME_PAYLOAD_BYTES = 3840;
export const FRAME_TOTAL_BYTES = 3849;
const PROTOCOL_VERSION = 1;

export function encodeFrame(sequence: number, captureMs: number, pcm: ArrayBuffer): ArrayBuffer {
  if (pcm.byteLength !== FRAME_PAYLOAD_BYTES) {
    throw new Error(`frame payload must be ${FRAME_PAYLOAD_BYTES} bytes, got ${pcm.byteLength}`);
  }
  const out = new ArrayBuffer(FRAME_TOTAL_BYTES);
  const view = new DataView(out);
  view.setUint8(0, PROTOCOL_VERSION);
  view.setUint32(1, sequence, true);
  view.setUint32(5, captureMs, true);
  new Uint8Array(out, 9).set(new Uint8Array(pcm));
  return out;
}
