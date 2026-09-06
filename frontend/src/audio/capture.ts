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
}

export class MicrophoneCapture {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;

  async start(handlers: CaptureHandlers): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    this.context = new AudioContext();
    await this.context.audioWorklet.addModule("/audio-worklet.js");

    const source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, "mosaique-capture");
    this.node.port.onmessage = (event) => {
      const data = event.data as { type: string; pcm?: ArrayBuffer; value?: number };
      if (data.type === "frame" && data.pcm) handlers.onFrame(data.pcm);
      else if (data.type === "level" && data.value !== undefined) handlers.onLevel(data.value);
    };
    source.connect(this.node);
    // Keep the worklet in the active audio graph without feeding microphone
    // audio back to the speakers.
    const silentOutput = this.context.createGain();
    silentOutput.gain.value = 0;
    this.node.connect(silentOutput);
    silentOutput.connect(this.context.destination);
  }

  async stop(): Promise<void> {
    this.node?.port.close();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    await this.context?.close();
    this.context = null;
    this.stream = null;
    this.node = null;
  }
}
