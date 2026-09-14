export type VoiceState = "idle" | "connecting" | "connected" | "reconnecting" | "failed";
export interface VoiceHandlers {
  sendSignal: (message: object) => void;
  onRemoteStream: (stream: MediaStream | null) => void;
  onState: (state: VoiceState) => void;
}
export interface SignalingPeer { participant_id: string; connection_id: string }
export interface VoiceSignal {
  v: 1;
  type: "rtc.offer" | "rtc.answer" | "rtc.ice";
  from_participant_id: string;
  connection_id: string;
  target_connection_id: string;
  negotiation_id: string;
  sdp?: string;
  candidate?: string;
  sdp_mid?: string | null;
  sdp_m_line_index?: number | null;
}
interface Session {
  id: string;
  pc: RTCPeerConnection;
  candidates: RTCIceCandidateInit[];
  remote: boolean;
  timer?: ReturnType<typeof setTimeout>;
}
interface Peer extends SignalingPeer {
  chain: Promise<void>;
  queued: number;
  session?: Session;
  attempts: number;
  seen: Set<string>;
  early: Map<string, RTCIceCandidateInit[]>;
}
const MAX_CANDIDATES = 128;
const MAX_ATTEMPTS = 3;
const RECOVERY_MS = 10_000;

/** Audio connections scoped to websocket generations and individual negotiations. */
export class WebRTCVoice {
  private peers = new Map<string, Peer>();
  private selfId: string | null = null;
  private connectionId: string | null = null;
  private localStream: MediaStream | null = null;
  private config: RTCConfiguration | null = null;
  private pending: VoiceSignal[] = [];
  private muted = false;

  constructor(private readonly handlers: VoiceHandlers) {}

  setConnection(selfId: string, connectionId: string): void {
    if (this.selfId === selfId && this.connectionId === connectionId) return;
    this.resetPeers();
    this.selfId = selfId;
    this.connectionId = connectionId;
  }

  /** Full authoritative rtc.peers snapshot, supplied after hello.ok. */
  setPeers(list: readonly SignalingPeer[]): void {
    if (!this.connectionId) return;
    const next = new Map(list.filter(p => p.participant_id !== this.selfId && p.connection_id)
      .map(p => [p.participant_id, p]));
    for (const [id, peer] of this.peers) {
      if (next.get(id)?.connection_id !== peer.connection_id) {
        this.peers.delete(id);
        this.dispose(peer);
        this.handlers.onRemoteStream(null);
      }
    }
    for (const [id, value] of next) {
      if (!this.peers.has(id)) this.peers.set(id, {
        ...value, chain: Promise.resolve(), queued: 0, attempts: 0, seen: new Set(), early: new Map(),
      });
    }
    this.startReady();
  }

  setIceServers(servers: RTCIceServer[], policy?: RTCIceTransportPolicy): void {
    this.config = { iceServers: servers, ...(policy ? { iceTransportPolicy: policy } : {}) };
    this.startReady();
    for (const signal of this.pending.splice(0)) void this.handleSignal(signal);
  }

  setLocalStream(stream: MediaStream | null): void {
    this.localStream = stream;
    stream?.getAudioTracks().forEach(track => { track.enabled = !this.muted; });
    for (const peer of this.peers.values()) {
      void this.enqueue(peer, async () => {
        const session = peer.session;
        if (!session) return;
        const sender = session.pc.getSenders().find(s => s.track?.kind === "audio" || s.track === null);
        if (sender) await sender.replaceTrack(this.localStream?.getAudioTracks()[0] ?? null);
      });
    }
  }

  private current(peer: Peer, session?: Session): boolean {
    return !!this.connectionId && this.peers.get(peer.participant_id) === peer &&
      (!session || peer.session === session);
  }
  private offers(peer: Peer): boolean { return !!this.selfId && this.selfId < peer.participant_id; }
  private enqueue(peer: Peer, action: () => Promise<void>): Promise<void> {
    if (peer.queued >= MAX_CANDIDATES) return Promise.resolve();
    peer.queued++;
    peer.chain = peer.chain.then(async () => {
      if (this.current(peer)) await action();
    }).catch(() => {
      if (this.current(peer)) this.recover(peer);
    }).finally(() => { peer.queued--; });
    return peer.chain;
  }
  private startReady(): void {
    if (!this.config) return;
    for (const peer of this.peers.values()) if (this.offers(peer)) {
      void this.enqueue(peer, async () => { if (!peer.session && !peer.attempts) await this.offer(peer); });
    }
  }

  async handleSignal(input: unknown): Promise<void> {
    if (!input || typeof input !== "object") return;
    const m = input as VoiceSignal;
    if (m.v !== 1 || !["rtc.offer", "rtc.answer", "rtc.ice"].includes(m.type) ||
      typeof m.negotiation_id !== "string" || !m.negotiation_id || m.negotiation_id.length > 256 ||
      m.target_connection_id !== this.connectionId) return;
    const peer = this.peers.get(m.from_participant_id);
    if (!peer || peer.connection_id !== m.connection_id) return;
    if (m.type === "rtc.ice" ? typeof m.candidate !== "string" || m.candidate.length > 8192 :
      typeof m.sdp !== "string" || m.sdp.length > 262144) return;
    if (!this.config) {
      if (this.pending.length < MAX_CANDIDATES) this.pending.push({ ...m });
      return;
    }
    return this.enqueue(peer, async () => {
      if (m.type === "rtc.offer") {
        if (this.offers(peer) || peer.seen.has(m.negotiation_id) || peer.attempts >= MAX_ATTEMPTS) return;
        const session = this.createSession(peer, m.negotiation_id);
        await session.pc.setRemoteDescription({ type: "offer", sdp: m.sdp });
        if (!this.current(peer, session)) return;
        // Answer on the offered audio transceiver. Pre-creating a separate
        // transceiver can leave capture attached to an unnegotiated m-line.
        const audio = session.pc.getTransceivers().find(t => t.receiver.track.kind === "audio");
        if (audio) {
          audio.direction = "sendrecv";
          await audio.sender.replaceTrack(this.localStream?.getAudioTracks()[0] ?? null);
          if (!this.current(peer, session)) return;
        }
        session.remote = true;
        await this.flush(peer, session);
        if (!this.current(peer, session)) return;
        const answer = await session.pc.createAnswer();
        if (!this.current(peer, session)) return;
        await session.pc.setLocalDescription(answer);
        if (this.current(peer, session)) this.send(peer, session, "rtc.answer", { sdp: session.pc.localDescription?.sdp ?? answer.sdp });
      } else if (m.type === "rtc.answer") {
        const session = peer.session;
        if (!this.offers(peer) || !session || session.id !== m.negotiation_id || session.remote) return;
        await session.pc.setRemoteDescription({ type: "answer", sdp: m.sdp });
        if (!this.current(peer, session)) return;
        session.remote = true;
        await this.flush(peer, session);
      } else {
        const candidate = { candidate: m.candidate, sdpMid: m.sdp_mid, sdpMLineIndex: m.sdp_m_line_index };
        const session = peer.session;
        if (session?.id === m.negotiation_id) {
          if (session.remote) await session.pc.addIceCandidate(candidate);
          else if (session.candidates.length < MAX_CANDIDATES) session.candidates.push(candidate);
        } else if (!this.offers(peer) && !peer.seen.has(m.negotiation_id) && peer.attempts < MAX_ATTEMPTS) {
          const count = [...peer.early.values()].reduce((sum, items) => sum + items.length, 0);
          if (count < MAX_CANDIDATES) {
            const items = peer.early.get(m.negotiation_id) ?? [];
            items.push(candidate);
            peer.early.set(m.negotiation_id, items);
          }
        }
      }
    });
  }

  private createSession(peer: Peer, id: string): Session {
    this.dispose(peer);
    // Count constructor failures too, so unavailable WebRTC cannot loop forever.
    peer.attempts++;
    peer.seen.add(id);
    const pc = new RTCPeerConnection(this.config!);
    const session: Session = { id, pc, candidates: peer.early.get(id) ?? [], remote: false };
    peer.early.clear();
    peer.session = session;
    const track = this.localStream?.getAudioTracks()[0];
    if (this.offers(peer)) {
      if (track && this.localStream) pc.addTrack(track, this.localStream);
      else pc.addTransceiver("audio", { direction: "sendrecv" });
    }
    pc.onicecandidate = event => {
      if (!this.current(peer, session) || !event.candidate) return;
      this.send(peer, session, "rtc.ice", { candidate: event.candidate.candidate,
        sdp_mid: event.candidate.sdpMid, sdp_m_line_index: event.candidate.sdpMLineIndex });
    };
    pc.ontrack = event => {
      if (this.current(peer, session)) this.handlers.onRemoteStream(event.streams[0] ?? new MediaStream([event.track]));
    };
    pc.onconnectionstatechange = () => {
      if (!this.current(peer, session)) return;
      if (pc.connectionState === "connected") {
        clearTimeout(session.timer);
        session.timer = undefined;
        this.handlers.onState("connected");
      } else if (pc.connectionState === "failed" || pc.connectionState === "disconnected") this.recover(peer);
    };
    this.handlers.onState(peer.attempts === 1 ? "connecting" : "reconnecting");
    this.arm(peer, session);
    return session;
  }
  private async offer(peer: Peer): Promise<void> {
    const session = this.createSession(peer, crypto.randomUUID());
    const offer = await session.pc.createOffer();
    if (!this.current(peer, session)) return;
    await session.pc.setLocalDescription(offer);
    if (this.current(peer, session)) this.send(peer, session, "rtc.offer", { sdp: session.pc.localDescription?.sdp ?? offer.sdp });
  }
  private send(peer: Peer, session: Session, type: VoiceSignal["type"], fields: object): void {
    this.handlers.sendSignal({ v: 1, type, connection_id: this.connectionId,
      target_participant_id: peer.participant_id, target_connection_id: peer.connection_id,
      negotiation_id: session.id, ...fields });
  }
  private async flush(peer: Peer, session: Session): Promise<void> {
    for (const candidate of session.candidates.splice(0)) {
      if (!this.current(peer, session)) return;
      await session.pc.addIceCandidate(candidate);
    }
  }
  private recover(peer: Peer): void {
    this.handlers.onState("reconnecting");
    if (peer.session) this.arm(peer, peer.session);
    else this.handlers.onState("failed");
  }
  private arm(peer: Peer, session: Session): void {
    if (session.timer !== undefined) return;
    session.timer = setTimeout(() => {
      session.timer = undefined;
      if (!this.current(peer, session)) return;
      if (this.offers(peer) && peer.attempts < MAX_ATTEMPTS) {
        void this.enqueue(peer, async () => {
          if (this.current(peer, session)) await this.offer(peer);
        });
      } else {
        this.dispose(peer);
        this.handlers.onRemoteStream(null);
        this.handlers.onState("failed");
      }
    }, RECOVERY_MS);
  }
  private dispose(peer: Peer): void {
    const session = peer.session;
    peer.session = undefined;
    if (!session) return;
    clearTimeout(session.timer);
    session.pc.onicecandidate = null;
    session.pc.ontrack = null;
    session.pc.onconnectionstatechange = null;
    session.pc.close();
  }
  private resetPeers(): void {
    for (const peer of this.peers.values()) this.dispose(peer);
    this.peers.clear();
    this.pending = [];
    this.handlers.onRemoteStream(null);
    this.handlers.onState("idle");
  }
  setMuted(muted: boolean): void {
    this.muted = muted;
    this.localStream?.getAudioTracks().forEach(track => { track.enabled = !muted; });
  }
  close(): void {
    this.connectionId = null;
    this.selfId = null;
    this.resetPeers();
    this.localStream = null;
  }
}
