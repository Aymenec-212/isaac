import { afterEach, expect, it, vi } from "vitest";
import { MeetingClient } from "../client";
import { TranscriptReconciler } from "../reconciler";

afterEach(() => vi.unstubAllGlobals());

it("a healthy peer cannot overwrite this participant's ASR outage", () => {
  let socket: { onmessage: (event: { data: string }) => void; close: () => void };
  vi.stubGlobal("window", { location: { protocol: "https:", host: "test" } });
  vi.stubGlobal("WebSocket", class {
    constructor() { socket = this as unknown as typeof socket; }
    close() {}
  });
  const onStreamStatus = vi.fn();
  const client = new MeetingClient("m", "t", {
    onTranscript: vi.fn(), onRoster: vi.fn(), onHelloOk: vi.fn(),
    onMeetingState: vi.fn(), onConnectionState: vi.fn(), onStreamStatus,
    onError: vi.fn(),
  });
  client.connect();
  const receive = (message: object) => socket.onmessage({ data: JSON.stringify(message) });
  receive({ type: "hello.ok", participant_id: "self" });
  receive({ type: "stream.status", participant_id: "self", status: "unavailable" });
  receive({ type: "stream.status", participant_id: "peer", status: "transcribing" });
  expect(onStreamStatus).toHaveBeenCalledTimes(1);
  expect(onStreamStatus).toHaveBeenCalledWith("unavailable", 0);
  client.close();
});

it("a live outage gap remains a gap and cannot be overwritten by later text", () => {
  const reconciler = new TranscriptReconciler();
  reconciler.apply({ type: "transcript.segment.final", participant_id: "p", sequence: 1,
    revision: 1, segment_id: "gap", status: "gap", text: "[transcription indisponible]",
    start_ms: 0, end_ms: 1000 });
  expect(reconciler.apply({ type: "transcript.delta", participant_id: "p", sequence: 1,
    revision: 2, text: "late", start_ms: 0 })).toBe(false);
  expect(reconciler.ordered()[0]?.status).toBe("gap");
});
