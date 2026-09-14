import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WebRTCVoice, type VoiceSignal } from "../webrtc";

class FakePC {
  static instances: FakePC[] = [];
  static offer: (() => Promise<RTCSessionDescriptionInit>) | undefined;
  connectionState = "new";
  localDescription: RTCSessionDescriptionInit | null = null;
  remoteDescription: RTCSessionDescriptionInit | null = null;
  onicecandidate: ((event: any) => void) | null = null;
  ontrack: ((event: any) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  sender = { track: null as MediaStreamTrack | null, replaceTrack: vi.fn(async () => {}) };
  close = vi.fn();
  addTrack = vi.fn((track: MediaStreamTrack) => { this.sender.track = track; });
  addTransceiver = vi.fn();
  getSenders = () => [this.sender];
  getTransceivers = () => [{ receiver: { track: { kind: "audio" } }, sender: this.sender, direction: "recvonly" }];
  createOffer = vi.fn(() => FakePC.offer?.() ?? Promise.resolve({ type: "offer" as const, sdp: "offer" }));
  createAnswer = vi.fn(async () => ({ type: "answer" as const, sdp: "answer" }));
  setLocalDescription = vi.fn(async (description: RTCSessionDescriptionInit) => { this.localDescription = description; });
  setRemoteDescription = vi.fn(async (description: RTCSessionDescriptionInit) => { this.remoteDescription = description; });
  addIceCandidate = vi.fn(async (_candidate: RTCIceCandidateInit) => {});
  constructor(readonly config: RTCConfiguration) { FakePC.instances.push(this); }
}
class FakeStream {
  constructor(readonly tracks: MediaStreamTrack[]) {}
  getAudioTracks() { return this.tracks; }
}
const settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const signal = (overrides: Partial<VoiceSignal> = {}): VoiceSignal => ({
  v: 1, type: "rtc.offer", from_participant_id: "a", connection_id: "remote",
  target_connection_id: "local", negotiation_id: "n1", sdp: "offer", ...overrides,
});
let voice: WebRTCVoice;
let send: ReturnType<typeof vi.fn>;
let state: ReturnType<typeof vi.fn>;
let remote: ReturnType<typeof vi.fn>;
function setup(self = "z", ready = true) {
  voice.setConnection(self, "local");
  voice.setPeers([{ participant_id: self === "a" ? "z" : "a", connection_id: "remote" }]);
  if (ready) voice.setIceServers([{ urls: "turn:example.test" }], "relay");
}

beforeEach(() => {
  vi.useFakeTimers();
  FakePC.instances = [];
  FakePC.offer = undefined;
  vi.stubGlobal("RTCPeerConnection", FakePC);
  vi.stubGlobal("MediaStream", FakeStream);
  let id = 0;
  vi.stubGlobal("crypto", { randomUUID: () => "local-n" + ++id });
  send = vi.fn(); state = vi.fn(); remote = vi.fn();
  voice = new WebRTCVoice({ sendSignal: send, onState: state, onRemoteStream: remote });
});
afterEach(() => { voice.close(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("WebRTCVoice generation-bound signaling", () => {
  it("waits for config before answering and uses the exact snake_case wire contract", async () => {
    setup("z", false);
    await voice.handleSignal(signal());
    expect(FakePC.instances).toHaveLength(0);
    voice.setIceServers([{ urls: "turn:example.test" }], "relay");
    await settle();
    const pc = FakePC.instances[0]!;
    expect(pc.config).toEqual({ iceServers: [{ urls: "turn:example.test" }], iceTransportPolicy: "relay" });
    expect(send).toHaveBeenCalledWith({
      v: 1, type: "rtc.answer", connection_id: "local", target_connection_id: "remote",
      target_participant_id: "a", negotiation_id: "n1", sdp: "answer",
    });
    pc.onicecandidate?.({ candidate: { candidate: "candidate", sdpMid: "0", sdpMLineIndex: 0 } });
    expect(send).toHaveBeenLastCalledWith({
      v: 1, type: "rtc.ice", connection_id: "local", target_connection_id: "remote",
      target_participant_id: "a", negotiation_id: "n1", candidate: "candidate", sdp_mid: "0", sdp_m_line_index: 0,
    });
  });

  it("uses only the lower participant as offerer and ignores duplicate offers", async () => {
    setup(); await settle();
    expect(FakePC.instances).toHaveLength(0);
    await Promise.all([voice.handleSignal(signal()), voice.handleSignal(signal())]);
    expect(FakePC.instances).toHaveLength(1);
    expect(send).toHaveBeenCalledTimes(1);
    voice.close(); setup("a"); await settle();
    expect(send).toHaveBeenLastCalledWith(expect.objectContaining({ type: "rtc.offer" }));
    await voice.handleSignal(signal({ from_participant_id: "z" }));
    expect(FakePC.instances).toHaveLength(2);
  });

  it("rejects absent, wrong sender, wrong target and unknown participant generations", async () => {
    setup();
    for (const patch of [
      { connection_id: "old" }, { target_connection_id: "old" },
      { from_participant_id: "stranger" }, { negotiation_id: "" }, { v: 2 },
    ]) await voice.handleSignal({ ...signal(), ...patch });
    await voice.handleSignal({ type: "rtc.offer", from_participant_id: "a", sdp: "offer" });
    expect(FakePC.instances).toHaveLength(0);
  });

  it("bounds early ICE and flushes only the matching negotiation after remote SDP", async () => {
    setup();
    for (let i = 0; i < 150; i++) await voice.handleSignal(signal({
      type: "rtc.ice", candidate: "candidate-" + i,
    }));
    await voice.handleSignal(signal());
    const pc = FakePC.instances[0]!;
    expect(pc.addIceCandidate).toHaveBeenCalledTimes(128);
    expect(pc.setRemoteDescription.mock.invocationCallOrder[0]!).toBeLessThan(pc.addIceCandidate.mock.invocationCallOrder[0]!);
    await voice.handleSignal(signal({ negotiation_id: "n2" }));
    await voice.handleSignal(signal({ type: "rtc.ice", candidate: "stale", negotiation_id: "n1" }));
    expect(FakePC.instances[1]!.addIceCandidate).not.toHaveBeenCalled();
    expect(pc.close).toHaveBeenCalledOnce();
  });

  it("serializes answers behind pending local offers and rejects mismatched answers", async () => {
    let resolve!: (value: RTCSessionDescriptionInit) => void;
    FakePC.offer = () => new Promise(r => { resolve = r; });
    setup("a"); await settle();
    const pending = voice.handleSignal(signal({ type: "rtc.answer", from_participant_id: "z", negotiation_id: "local-n1", sdp: "answer" }));
    const pc = FakePC.instances[0]!;
    expect(pc.setRemoteDescription).not.toHaveBeenCalled();
    resolve({ type: "offer", sdp: "offer" });
    await pending;
    expect(pc.setLocalDescription.mock.invocationCallOrder[0]!).toBeLessThan(pc.setRemoteDescription.mock.invocationCallOrder[0]!);
    await voice.handleSignal(signal({ type: "rtc.answer", from_participant_id: "z", negotiation_id: "wrong" }));
    expect(pc.setRemoteDescription).toHaveBeenCalledOnce();
  });

  it("invalidates pending work and captured callbacks on remote reconnect", async () => {
    let resolve!: (value: RTCSessionDescriptionInit) => void;
    FakePC.offer = () => new Promise(r => { resolve = r; });
    setup("a"); await settle();
    const pc = FakePC.instances[0]!;
    const ice = pc.onicecandidate!;
    const track = pc.ontrack!;
    const connection = pc.onconnectionstatechange!;
    FakePC.offer = undefined;
    voice.setPeers([{ participant_id: "z", connection_id: "replacement" }]);
    await settle();
    send.mockClear(); remote.mockClear(); state.mockClear();
    resolve({ type: "offer", sdp: "stale" });
    ice({ candidate: { candidate: "stale" } });
    track({ streams: [] });
    pc.connectionState = "connected"; connection();
    await settle();
    expect(send).not.toHaveBeenCalled();
    expect(remote).not.toHaveBeenCalled();
    expect(state).not.toHaveBeenCalled();
    expect(pc.setLocalDescription).not.toHaveBeenCalled();
    expect(pc.close).toHaveBeenCalledOnce();
    expect(FakePC.instances).toHaveLength(2);
  });

  it("requires a fresh roster after local reconnect and clears queued preconfig signals", async () => {
    setup("z", false);
    await voice.handleSignal(signal());
    voice.setConnection("z", "new-local");
    voice.setIceServers([]);
    await settle();
    expect(FakePC.instances).toHaveLength(0);
    voice.setPeers([{ participant_id: "a", connection_id: "remote" }]);
    await voice.handleSignal(signal());
    expect(FakePC.instances).toHaveLength(0);
    await voice.handleSignal(signal({ target_connection_id: "new-local" }));
    expect(FakePC.instances).toHaveLength(1);
  });

  it("supports streamless tracks and attaches late capture to the existing sender", async () => {
    setup(); await voice.handleSignal(signal());
    const pc = FakePC.instances[0]!;
    const track = { kind: "audio", enabled: true } as MediaStreamTrack;
    pc.ontrack?.({ streams: [], track });
    expect(remote.mock.calls.at(-1)?.[0].getAudioTracks()).toEqual([track]);
    voice.setMuted(true);
    voice.setLocalStream(new FakeStream([track]) as unknown as MediaStream);
    await settle();
    expect(track.enabled).toBe(false);
    expect(pc.sender.replaceTrack).toHaveBeenCalledWith(track);
    voice.setLocalStream(null); await settle();
    expect(pc.sender.replaceTrack).toHaveBeenLastCalledWith(null);
    expect(pc.addTransceiver).not.toHaveBeenCalled();
  });

  it("retries with fresh negotiations at most twice, then stops until a generation changes", async () => {
    setup("a"); await settle();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(FakePC.instances).toHaveLength(3);
    expect(new Set(send.mock.calls.map(([m]) => m.negotiation_id)).size).toBe(3);
    expect(state).toHaveBeenLastCalledWith("failed");
    await vi.advanceTimersByTimeAsync(60_000);
    voice.setPeers([{ participant_id: "z", connection_id: "remote" }]);
    await settle();
    expect(FakePC.instances).toHaveLength(3);
    voice.setPeers([{ participant_id: "z", connection_id: "new" }]);
    await settle();
    expect(FakePC.instances).toHaveLength(4);
  });

  it("cancels disconnect recovery on reconnection and all callbacks on close", async () => {
    setup("a"); await settle();
    const pc = FakePC.instances[0]!;
    pc.connectionState = "connected"; pc.onconnectionstatechange?.();
    pc.connectionState = "disconnected"; pc.onconnectionstatechange?.();
    pc.connectionState = "connected"; pc.onconnectionstatechange?.();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(FakePC.instances).toHaveLength(1);
    voice.close();
    send.mockClear();
    await vi.advanceTimersByTimeAsync(60_000);
    await voice.handleSignal(signal());
    expect(send).not.toHaveBeenCalled();
    expect(pc.ontrack).toBeNull();
    expect(state).toHaveBeenLastCalledWith("idle");
  });

  it("contains SDP failures and recovers without unhandled rejections", async () => {
    setup("a"); await settle();
    FakePC.instances[0]!.setRemoteDescription.mockRejectedValueOnce(new Error("bad SDP"));
    await expect(voice.handleSignal(signal({
      type: "rtc.answer", from_participant_id: "z", negotiation_id: "local-n1",
    }))).resolves.toBeUndefined();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakePC.instances).toHaveLength(2);
  });
});
