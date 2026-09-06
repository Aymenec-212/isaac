/** Meeting WebSocket client (tech spec 7). Reconnect arrives in Slice 3. */
import { encodeFrame } from "./frames";
import type { TranscriptMessage } from "./reconciler";

export type ConnectionState = "connecting" | "live" | "closed" | "error";

export interface MeetingClientHandlers {
  onTranscript: (message: TranscriptMessage) => void;
  onHelloOk: (participantId: string) => void;
  onMeetingState: (state: string) => void;
  onConnectionState: (state: ConnectionState) => void;
  onError: (code: string, message: string) => void;
}

export class MeetingClient {
  private socket: WebSocket | null = null;
  private sequence = 0;
  private captureStartedAt = 0;

  constructor(
    private readonly meetingId: string,
    private readonly sessionToken: string,
    private readonly handlers: MeetingClientHandlers,
  ) {}

  connect(): void {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${scheme}://${window.location.host}/api/ws/meetings/${this.meetingId}`;
    this.handlers.onConnectionState("connecting");
    this.socket = new WebSocket(url);
    this.socket.binaryType = "arraybuffer";

    this.socket.onopen = () => {
      this.captureStartedAt = Date.now();
      this.send({
        v: 1,
        type: "hello",
        session_token: this.sessionToken,
        last_ack_sequence: null,
        client: { ua: navigator.userAgent, sample_rate: 24000 },
      });
    };

    this.socket.onmessage = (event) => {
      const message = JSON.parse(event.data as string);
      switch (message.type) {
        case "hello.ok":
          this.handlers.onConnectionState("live");
          this.handlers.onHelloOk(message.participant_id);
          break;
        case "transcript.delta":
        case "transcript.segment.final":
          this.handlers.onTranscript(message as TranscriptMessage);
          break;
        case "meeting.state":
          this.handlers.onMeetingState(message.state);
          break;
        case "error":
          this.handlers.onError(message.code, message.message);
          if (message.fatal) this.handlers.onConnectionState("error");
          break;
      }
    };

    this.socket.onclose = () => this.handlers.onConnectionState("closed");
    this.socket.onerror = () => this.handlers.onConnectionState("error");
  }

  sendAudio(pcm: ArrayBuffer): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    const captureMs = Date.now() - this.captureStartedAt;
    this.socket.send(encodeFrame(this.sequence++, captureMs, pcm));
  }

  private send(payload: unknown): void {
    this.socket?.send(JSON.stringify(payload));
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
  }
}
