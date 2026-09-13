import { afterEach, expect, it, vi } from "vitest";
import { MeetingClient } from "../client";

it("retains a capture across reconnect, buffers before hello, and rotates on reload", () => {
  vi.useFakeTimers();
  class Socket {
    static OPEN = 1;
    static instances: Socket[] = [];
    readyState = 1;
    onopen = () => {};
    onclose = () => {};
    onmessage = (_: { data: string }) => {};
    onerror = () => {};
    sent: (string | ArrayBuffer)[] = [];
    constructor() { Socket.instances.push(this); }
    send(data: string | ArrayBuffer) { this.sent.push(data); }
    close() {}
  }
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("window", { location: { protocol: "https:", host: "test" } });
  vi.stubGlobal("navigator", { userAgent: "test" });
  const handlers = { onTranscript: vi.fn(), onRoster: vi.fn(), onHelloOk: vi.fn(),
    onMeetingState: vi.fn(), onConnectionState: vi.fn(), onStreamStatus: vi.fn(), onError: vi.fn() };
  const client = new MeetingClient("m", "t", handlers);
  client.connect();
  const a = Socket.instances[0]!;
  a.onopen();
  const firstCapture = JSON.parse(a.sent[0] as string).capture_id;
  client.sendAudio(new ArrayBuffer(3840));
  expect(a.sent.length).toBe(1);
  a.onmessage({ data: JSON.stringify({ type: "hello.ok", participant_id: "p" }) });
  expect(a.sent.length).toBe(2);
  a.onclose();
  vi.advanceTimersByTime(500);
  const b = Socket.instances[1]!;
  b.onopen();
  expect(JSON.parse(b.sent[0] as string).capture_id).toBe(firstCapture);
  a.onclose(); // a stale event cannot schedule another connection
  vi.advanceTimersByTime(600);
  expect(Socket.instances.length).toBe(2);
  client.close();
  const reloaded = new MeetingClient("m", "t", handlers);
  reloaded.connect();
  const c = Socket.instances[2]!;
  c.onopen();
  expect(JSON.parse(c.sent[0] as string).capture_id).not.toBe(firstCapture);
  reloaded.close();
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
