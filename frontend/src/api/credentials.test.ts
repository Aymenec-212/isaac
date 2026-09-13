import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { meetingCredentials, token } from "./credentials";
import { api, type JoinResponse } from "./client";
const id = "01AAAAAAAAAAAAAAAAAAAAAAAA";
function memoryStorage() {
  const values = new Map<string, string>();
  return { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key) };
}
function joined(can_manage = false): JoinResponse {
  return { meeting: { id }, participant: { id: "p" }, session_token: "guest", can_manage } as JoinResponse;
}
beforeEach(() => vi.stubGlobal("window", { localStorage: memoryStorage(), sessionStorage: memoryStorage() }));
afterEach(() => vi.unstubAllGlobals());

it("keeps retries on the same nonce and separates meetings", () => {
  expect(meetingCredentials.nonce(id)).toBe(meetingCredentials.nonce(id));
  expect(meetingCredentials.nonce(id)).not.toBe(meetingCredentials.nonce("other"));
});
it("uses a guest's meeting token despite an unrelated host login", () => {
  token.set("unrelated");
  meetingCredentials.save(joined());
  expect(meetingCredentials.bearer(id)).toBe("guest");
  expect(meetingCredentials.get(id)?.participant.id).toBe("p");
});
it("uses the verified host credential only while that host remains logged in", () => {
  token.set("owner");
  meetingCredentials.save(joined(true));
  expect(meetingCredentials.bearer(id)).toBe("owner");
  token.clear();
  expect(meetingCredentials.bearer(id)).toBe("guest");
});
it("sends the guest credential for transcript, outputs and audio", async () => {
  token.set("unrelated");
  meetingCredentials.save(joined());
  const fetcher = vi.fn(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  await api.transcript(id);
  await api.outputs(id);
  await api.audio(id, "session");
  for (const call of fetcher.mock.calls as unknown as [string, RequestInit][]) {
    expect(new Headers(call[1].headers).get("Authorization")).toBe("Bearer guest");
  }
});
it("a failed join response retries the same key then persists the successful identity", async () => {
  const bodies: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
    bodies.push(String(init.body));
    if (bodies.length === 1) throw new Error("response lost");
    return new Response(JSON.stringify(joined()));
  }));
  await expect(api.join(id, "A", "invite")).rejects.toThrow();
  await api.join(id, "A", "invite");
  expect(JSON.parse(bodies[0]!)).toEqual(JSON.parse(bodies[1]!));
  expect(meetingCredentials.get(id)?.session_token).toBe("guest");
});
