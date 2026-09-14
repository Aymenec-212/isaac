import { afterEach, expect, it, vi } from "vitest";
import { MeetingClient } from "../client";

class Socket {
  static OPEN = 1;
  static current: Socket;
  readyState = 1;
  sent: (string | ArrayBuffer)[] = [];
  onopen = () => {};
  onmessage = (_: { data: string }) => {};
  constructor() { Socket.current = this; }
  send(data: string | ArrayBuffer) { this.sent.push(data); }
  close() {}
  receive(data: object) { this.onmessage({ data: JSON.stringify(data) }); }
}
let client: MeetingClient;
function setup(onEndRequested = async () => {}) {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("window", { location: { protocol: "https:", host: "test" } });
  vi.stubGlobal("navigator", { userAgent: "test" });
  client = new MeetingClient("m", "t", { onTranscript: vi.fn(), onRoster: vi.fn(),
    onHelloOk: vi.fn(), onMeetingState: vi.fn(), onConnectionState: vi.fn(),
    onStreamStatus: vi.fn(), onError: vi.fn(), onEndRequested });
  client.connect();
  const socket = Socket.current;
  socket.onopen();
  socket.receive({ type: "hello.ok", participant_id: "p", connection_id: "c" });
  return socket;
}
afterEach(() => { client.close(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("awaits final capture before sending the sequence-bound marker and seals later frames", async () => {
  let finish!: () => void;
  const socket = setup(() => new Promise<void>(resolve => { finish = resolve; }));
  socket.receive({ type: "meeting.end_requested", request_id: "end" });
  client.sendAudio(new ArrayBuffer(3840));
  expect(socket.sent).toHaveLength(2);
  finish();
  await Promise.resolve();
  const marker = JSON.parse(socket.sent.at(-1) as string);
  expect(marker).toMatchObject({ type: "audio.flush", request_id: "end", last_sequence: 0 });
  client.sendAudio(new ArrayBuffer(3840));
  expect(socket.sent).toHaveLength(3);
  socket.receive({ type: "audio.flush.ok", request_id: "end", last_sequence: 0 });
});

it("rejects mismatched acknowledgements and resolves all callers on timeout", async () => {
  const socket = setup();
  const first = client.flush(100, "end");
  const second = client.flush(100, "end");
  socket.receive({ type: "audio.flush.ok", request_id: "old", last_sequence: -1 });
  socket.receive({ type: "audio.flush.ok", request_id: "end", last_sequence: 5 });
  await vi.advanceTimersByTimeAsync(100);
  expect(await Promise.all([first, second])).toEqual([false, false]);
});

it("supersedes a voluntary leave marker with the server end request", async () => {
  const socket = setup();
  const leave = client.flush();
  const end = client.flush(100, "end");
  expect(await leave).toBe(false);
  socket.receive({ type: "audio.flush.ok", request_id: "end", last_sequence: -1 });
  expect(await end).toBe(true);
});
