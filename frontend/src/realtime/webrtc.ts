import type { RTCSignal } from "./client";

export type VoiceState = "idle" | "connecting" | "connected" | "reconnecting" | "failed";

export interface VoiceHandlers {
  sendSignal: (message: object) => void;
  onRemoteStream: (stream: MediaStream | null) => void;
  onState: (state: VoiceState) => void;
}

/** Two-party, server-signaled WebRTC audio mesh. Media never passes through the app server. */
export class WebRTCVoice {
  private readonly peers = new Map<string, RTCPeerConnection>();
  private readonly pendingCandidates = new Map<string, RTCIceCandidateInit[]>();
  private readonly knownParticipants = new Set<string>();
  private localStream: MediaStream | null = null;
  private selfId: string | null = null;
  private iceServers: RTCIceServer[] = [];
  private iceReady = false;

  constructor(private readonly handlers: VoiceHandlers) {}

  setIceServers(servers: RTCIceServer[]): void {
    this.iceServers = servers;
    this.iceReady = true;
    for (const peerId of this.knownParticipants) void this.maybeOffer(peerId);
  }

  setSelfId(id: string): void {
    this.selfId = id;
    for (const peerId of this.knownParticipants) void this.maybeOffer(peerId);
  }

  setLocalStream(stream: MediaStream): void {
    this.localStream = stream;
    for (const peer of this.peers.values()) {
      const track = stream.getAudioTracks()[0];
      if (!track) continue;
      const sender = peer.getSenders().find((candidate) =>
        candidate.track?.kind === "audio" || candidate.track === null,
      );
      if (sender) void sender.replaceTrack(track);
      else peer.addTrack(track, stream);
    }
  }

  participantJoined(participantId: string): void {
    if (participantId === this.selfId) return;
    this.knownParticipants.add(participantId);
    void this.maybeOffer(participantId);
  }

  participantLeft(participantId: string): void {
    this.knownParticipants.delete(participantId);
    this.closePeer(participantId);
    if (this.peers.size === 0) this.handlers.onRemoteStream(null);
  }

  private async maybeOffer(participantId: string): Promise<void> {
    if (!this.iceReady || !this.selfId || this.selfId >= participantId || this.peers.has(participantId)) return;
    const peer = this.ensurePeer(participantId);
    this.handlers.onState("connecting");
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    this.handlers.sendSignal({ v: 1, type: "rtc.offer", target_participant_id: participantId, sdp: offer.sdp });
  }

  async handleSignal(message: RTCSignal): Promise<void> {
    const peer = this.ensurePeer(message.from_participant_id);
    if (message.type === "rtc.offer") {
      await peer.setRemoteDescription({ type: "offer", sdp: message.sdp });
      await this.flushCandidates(message.from_participant_id, peer);
      const answer = await peer.createAnswer();
      await peer.setLocalDescription(answer);
      this.handlers.sendSignal({ v: 1, type: "rtc.answer", target_participant_id: message.from_participant_id, sdp: answer.sdp });
    } else if (message.type === "rtc.answer") {
      await peer.setRemoteDescription({ type: "answer", sdp: message.sdp });
      await this.flushCandidates(message.from_participant_id, peer);
    } else {
      const candidate = { candidate: message.candidate, sdpMid: message.sdp_mid, sdpMLineIndex: message.sdp_m_line_index };
      if (peer.remoteDescription) await peer.addIceCandidate(candidate);
      else this.pendingCandidates.set(message.from_participant_id, [...(this.pendingCandidates.get(message.from_participant_id) ?? []), candidate]);
    }
  }

  private ensurePeer(participantId: string): RTCPeerConnection {
    const existing = this.peers.get(participantId);
    if (existing) return existing;
    const peer = new RTCPeerConnection({ iceServers: this.iceServers });
    this.peers.set(participantId, peer);
    const track = this.localStream?.getAudioTracks()[0];
    if (track && this.localStream) peer.addTrack(track, this.localStream);
    else peer.addTransceiver("audio", { direction: "sendrecv" });
    peer.onicecandidate = (event) => {
      if (!event.candidate) return;
      this.handlers.sendSignal({ v: 1, type: "rtc.ice", target_participant_id: participantId, ...event.candidate.toJSON() });
    };
    peer.ontrack = (event) => this.handlers.onRemoteStream(event.streams[0] ?? null);
    peer.onconnectionstatechange = () => {
      if (peer.connectionState === "connected") this.handlers.onState("connected");
      else if (peer.connectionState === "failed") this.handlers.onState("failed");
      else if (peer.connectionState === "disconnected") this.handlers.onState("reconnecting");
    };
    return peer;
  }

  private async flushCandidates(participantId: string, peer: RTCPeerConnection): Promise<void> {
    for (const candidate of this.pendingCandidates.get(participantId) ?? []) await peer.addIceCandidate(candidate);
    this.pendingCandidates.delete(participantId);
  }

  private closePeer(participantId: string): void {
    this.peers.get(participantId)?.close();
    this.peers.delete(participantId);
    this.pendingCandidates.delete(participantId);
  }

  setMuted(muted: boolean): void { this.localStream?.getAudioTracks().forEach((track) => { track.enabled = !muted; }); }

  close(): void {
    for (const participantId of this.peers.keys()) this.closePeer(participantId);
    this.localStream = null;
    this.handlers.onRemoteStream(null);
    this.handlers.onState("idle");
  }
}
