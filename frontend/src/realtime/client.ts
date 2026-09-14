/**
 * Meeting WebSocket client (tech spec 7).
 *
 * Reconnect is the substance here. The server holds a dropped stream open for
 * 30 s and resumes it in place, so the client's job is to come back inside
 * that window with its sequence intact and the audio it captured meanwhile.
 * Losing the socket therefore costs a pause, not a segment.
 */
import { encodeFrame } from "./frames";
import { FrameBuffer } from "./buffer";
import type { TranscriptMessage } from "./reconciler";
import { isRosterMessage, type RosterMessage } from "./roster";

export type ConnectionState = "connecting" | "live" | "reconnecting" | "closed" | "error";
export type StreamState = "listening" | "receiving" | "transcribing" | "delayed" | "unavailable";

/** Backoff between reconnect attempts, capped well inside the 30 s grace. */
const RETRY_DELAYS_MS = [500, 1_000, 2_000, 4_000, 8_000];
const CLIENT_PING_MS = 10_000;

export interface MeetingClientHandlers {
  onTranscript: (message: TranscriptMessage) => void;
  onRoster: (message: RosterMessage) => void;
  onHelloOk: (participantId: string, resumed: boolean, connectionId?: string) => void;
  onMeetingState: (state: string) => void;
  onConnectionState: (state: ConnectionState) => void;
  onStreamStatus: (status: StreamState, lagMs: number) => void;
  onError: (code: string, message: string) => void;
  onSignal?: (message: RTCSignal) => void;
  onPeers?: (peers: Array<{ participant_id: string; connection_id: string }>) => void;
  onEndRequested?: () => Promise<void>;
}

export type RTCSignal = { v: 1; connection_id: string; target_connection_id: string; negotiation_id: string } & (
  | { type: "rtc.offer"; from_participant_id: string; sdp: string }
  | { type: "rtc.answer"; from_participant_id: string; sdp: string }
  | { type: "rtc.ice"; from_participant_id: string; candidate: string; sdp_mid?: string | null; sdp_m_line_index?: number | null });

export class MeetingClient {
  private socket: WebSocket | null = null;
  private sequence = 0;
  private readonly captureId = crypto.randomUUID();
  private readyForAudio = false;
  private participantId: string | null = null;
  private captureStartedAt = 0;
  private attempt = 0;
  private closing = false;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly buffer = new FrameBuffer();
  private inputClosed = false;
  private flushWaiter: { requestId: string | null; sequence: number; resolve: (value: boolean) => void; timer: ReturnType<typeof setTimeout> } | null = null;

  constructor(
    private readonly meetingId: string,
    private readonly sessionToken: string,
    private readonly handlers: MeetingClientHandlers,
  ) {}

  connect(): void {
    if (this.closing) return;
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${scheme}://${window.location.host}/api/ws/meetings/${this.meetingId}`;
    this.handlers.onConnectionState(this.attempt === 0 ? "connecting" : "reconnecting");
    this.readyForAudio = false;
    const socket = new WebSocket(url);
    this.socket = socket;
    this.socket.binaryType = "arraybuffer";

    this.socket.onopen = () => {
      if (this.socket !== socket) return;
      if (this.captureStartedAt === 0) this.captureStartedAt = Date.now();
      this.send({
        v: 1,
        type: "hello",
        session_token: this.sessionToken,
        capture_id: this.captureId,
        // X-13: what we believe we got through, so the server can log a
        // disagreement. It trusts its own count, not ours.
        last_ack_sequence: this.sequence > 0 ? this.sequence - 1 : null,
        client: { ua: navigator.userAgent, sample_rate: 24000, voice: true },
      });
    };

    this.socket.onmessage = (event) => {
      if (this.socket !== socket) return;
      const message = JSON.parse(event.data as string);
      if (isRosterMessage(message)) {
        this.handlers.onRoster(message);
        return;
      }
      switch (message.type) {
        case "hello.ok":
          this.participantId = message.participant_id;
          this.readyForAudio = true;
          this.attempt = 0;
          this.handlers.onConnectionState("live");
          this.flushBuffer();
          this.startPinging();
          this.handlers.onHelloOk(message.participant_id, message.resume === true, message.connection_id);
          break;
        case "transcript.delta":
        case "transcript.segment.final":
          this.handlers.onTranscript(message as TranscriptMessage);
          break;
        case "stream.status":
          if (message.participant_id === this.participantId) {
            this.handlers.onStreamStatus(message.status as StreamState, message.lag_ms ?? 0);
          }
          break;
        case "meeting.state":
          this.handlers.onMeetingState(message.state);
          break;
        case "meeting.end_requested":
          void this.finishInput(message.request_id);
          break;
        case "rtc.peers":
          this.handlers.onPeers?.(message.peers);
          break;
        case "audio.flush.ok":
          if (this.flushWaiter && (message.request_id ?? null) === this.flushWaiter.requestId
              && message.last_sequence === this.flushWaiter.sequence) {
            clearTimeout(this.flushWaiter.timer);
            this.flushWaiter.resolve(true);
            this.flushWaiter = null;
          }
          break;
        case "rtc.offer":
        case "rtc.answer":
        case "rtc.ice":
          this.handlers.onSignal?.(message as RTCSignal);
          break;
        case "ping":
          // The server decides a silent socket is dead after 30 s, so this
          // answer is what keeps a listening-only participant connected.
          this.send({ v: 1, type: "pong", t: message.t });
          break;
        case "error":
          this.handlers.onError(message.code, message.message);
          if (message.fatal) {
            // A fatal error is a decision, not a glitch: do not fight it by
            // reconnecting into the same refusal.
            this.closing = true;
            this.handlers.onConnectionState("error");
          }
          break;
      }
    };

    this.socket.onclose = () => {
      if (this.socket !== socket) return;
      this.readyForAudio = false;
      this.stopPinging();
      if (this.closing) {
        this.handlers.onConnectionState("closed");
        return;
      }
      this.scheduleRetry();
    };
    this.socket.onerror = () => { if (this.socket === socket) socket.close(); };
  }

  private scheduleRetry(): void {
    const delay = RETRY_DELAYS_MS[Math.min(this.attempt, RETRY_DELAYS_MS.length - 1)];
    this.attempt += 1;
    this.handlers.onConnectionState("reconnecting");
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  private startPinging(): void {
    this.stopPinging();
    this.pingTimer = setInterval(() => this.send({ v: 1, type: "ping", t: Date.now() }), CLIENT_PING_MS);
  }

  private stopPinging(): void {
    if (this.pingTimer !== null) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  private flushBuffer(): void {
    for (const frame of this.buffer.drain()) {
      this.socket?.send(encodeFrame(frame.sequence, frame.sequence * 80, frame.pcm));
    }
  }

  sendAudio(pcm: ArrayBuffer): void {
    if (this.inputClosed) return;
    const sequence = this.sequence++;
    if (!this.readyForAudio || this.socket?.readyState !== WebSocket.OPEN) {
      // Offline: hold it. The sequence still advances, so what we send when we
      // get back continues where the server left off.
      this.buffer.push(sequence, pcm);
      return;
    }
    const captureMs = Date.now() - this.captureStartedAt;
    this.socket.send(encodeFrame(sequence, captureMs, pcm));
  }

  setPaused(paused: boolean): void {
    this.send({ v: 1, type: paused ? "audio.pause" : "audio.resume" });
  }

  sendSignal(message: object): void { if (this.readyForAudio && !this.inputClosed) this.send(message); }

  private async finishInput(requestId: string): Promise<void> {
    try { await this.handlers.onEndRequested?.(); }
    catch { this.handlers.onError("AUDIO_FLUSH_FAILED", "Microphone shutdown failed"); }
    finally { await this.flush(1_000, requestId); }
  }

  flush(timeoutMs = 1_000, requestId: string | null = null): Promise<boolean> {
    this.inputClosed = true;
    if (!this.readyForAudio || this.socket?.readyState !== WebSocket.OPEN) return Promise.resolve(false);
    if (this.flushWaiter && this.flushWaiter.requestId !== requestId) {
      const prior = this.flushWaiter;
      clearTimeout(prior.timer);
      this.flushWaiter = null;
      prior.resolve(false);
    }
    if (this.flushWaiter) return new Promise((resolve) => {
      const prior = this.flushWaiter!;
      const oldResolve = prior.resolve;
      prior.resolve = (value) => { oldResolve(value); resolve(value); };
    });
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        const waiter = this.flushWaiter;
        this.flushWaiter = null;
        waiter?.resolve(false);
      }, timeoutMs);
      this.flushWaiter = { requestId, sequence: this.sequence - 1, resolve, timer };
      this.send({ v: 1, type: "audio.flush", request_id: requestId, last_sequence: this.sequence - 1 });
    });
  }

  private send(payload: unknown): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(payload));
  }

  close(): void {
    this.closing = true;
    this.stopPinging();
    if (this.retryTimer !== null) clearTimeout(this.retryTimer);
    if (this.flushWaiter) {
      clearTimeout(this.flushWaiter.timer);
      this.flushWaiter.resolve(false);
      this.flushWaiter = null;
    }
    this.socket?.close();
    this.socket = null;
  }
}
