/**
 * Microphone capture pipeline (tech spec 8.2).
 *
 * Echo cancellation is on deliberately: in the prototype's operating model a
 * participant may hear the others through the same device, and without AEC
 * that far-end audio is attributed to the local speaker.
 */
export interface CaptureHandlers {
  onFrame: (pcm: ArrayBuffer) => void;
  onLevel: (level: number) => void;
  onStream?: (stream: MediaStream) => void;
}

export class MicrophoneCapture {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private muted = false;
  private stopped = false;
  private flushDone: (() => void) | null = null;
  private finishing: Promise<boolean> | null = null;

  async start(handlers: CaptureHandlers): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    if (this.stopped) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
      return;
    }
    this.stream.getAudioTracks().forEach((track) => { track.enabled = !this.muted; });
    handlers.onStream?.(this.stream);

    this.context = new AudioContext();
    await this.context.audioWorklet.addModule("/audio-worklet.js");
    if (this.stopped) return;

    const source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, "mosaique-capture");
    this.node.port.onmessage = (event) => {
      const data = event.data as { type: string; pcm?: ArrayBuffer; value?: number };
      if (data.type === "frame" && data.pcm && !this.muted) handlers.onFrame(data.pcm);
      else if (data.type === "level" && data.value !== undefined) handlers.onLevel(data.value);
      else if (data.type === "flushed") this.flushDone?.();
    };
    source.connect(this.node);
    // Keep the worklet in the active audio graph without feeding microphone
    // audio back to the speakers.
    const silentOutput = this.context.createGain();
    silentOutput.gain.value = 0;
    this.node.connect(silentOutput);
    silentOutput.connect(this.context.destination);
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    this.stream?.getAudioTracks().forEach((track) => { track.enabled = !muted; });
  }

  async stop(): Promise<void> {
    this.stopped = true;
    this.flushDone?.();
    this.node?.port.close();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.context = null;
    this.stream = null;
    this.node = null;
    this.muted = false;
  }

  /** Flush the padded partial frame before releasing capture. One bounded operation. */
  finish(): Promise<boolean> {
    if (this.finishing) return this.finishing;
    this.finishing = (async () => {
      let flushed = true;
      if (this.node && this.context?.state === "running") {
        flushed = await new Promise<boolean>((resolve) => {
          const timer = setTimeout(() => { this.flushDone = null; resolve(false); }, 750);
          this.flushDone = () => {
            clearTimeout(timer);
            this.flushDone = null;
            resolve(true);
          };
          this.node!.port.postMessage({ type: "flush" });
        });
      }
      await this.stop();
      return flushed;
    })();
    return this.finishing;
  }
}
