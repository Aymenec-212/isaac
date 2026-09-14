import { afterEach, expect, it, vi } from "vitest";
import { MicrophoneCapture } from "./capture";
import worklet from "../../public/audio-worklet.js?raw";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it("releases a microphone granted after capture was stopped", async () => {
  let grant!: (stream: MediaStream) => void;
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: () => new Promise(r => { grant = r; }) } });
  const capture = new MicrophoneCapture();
  const onStream = vi.fn();
  const start = capture.start({ onFrame: vi.fn(), onLevel: vi.fn(), onStream });
  await capture.stop();
  const stop = vi.fn();
  grant({ getTracks: () => [{ stop }] } as unknown as MediaStream);
  await start;
  expect(stop).toHaveBeenCalledOnce();
  expect(onStream).not.toHaveBeenCalled();
});

it("flushes a padded partial worklet frame before acknowledgement and stops producing", () => {
  const sent: Array<{ type: string; pcm?: ArrayBuffer }> = [];
  class Processor { port = { postMessage: (m: { type: string }) => sent.push(m), onmessage: (_: unknown) => {} }; }
  let factory!: new () => Processor & { process: (inputs: Float32Array[][]) => boolean };
  new Function("AudioWorkletProcessor", "sampleRate", "registerProcessor", worklet)(
    Processor, 48000, (_: string, ctor: typeof factory) => { factory = ctor; },
  );
  const processor = new factory();
  processor.process([[new Float32Array(128).fill(0.5)]]);
  processor.port.onmessage({ data: { type: "flush" } });
  expect(sent.map(m => m.type)).toEqual(["frame", "flushed"]);
  const pcm = new Int16Array(sent[0]!.pcm!);
  expect(pcm.length).toBe(1920);
  expect(pcm[0]).toBeGreaterThan(0);
  expect(pcm[1919]).toBe(0);
  processor.process([[new Float32Array(4096).fill(0.5)]]);
  expect(sent.length).toBe(2);
});
