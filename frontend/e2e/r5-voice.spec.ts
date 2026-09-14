/** Real Chromium RTP/signaling; fake microphone and server-side ASR/LLM only.
 * Setup and optional MOSAIQUE_R5_RELAY_ONLY=1: deploy/turn/README.md.
 */
import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { chromiumLaunch, isolateFromCdns } from "./launch";

const relayOnly = process.env.MOSAIQUE_R5_RELAY_ONLY === "1";
test.use({ launchOptions: chromiumLaunch, permissions: ["microphone"] });

declare global {
  interface Window {
    __r5: { peers: RTCPeerConnection[]; tracks: MediaStreamTrack[] };
  }
}

async function observeRTC(context: BrowserContext): Promise<void> {
  await isolateFromCdns(context);
  await context.addInitScript((forceRelay) => {
    const NativePeer = window.RTCPeerConnection;
    window.__r5 = { peers: [], tracks: [] };
    // Subclass the real constructor: no fake negotiation, tracks or getStats.
    window.RTCPeerConnection = class extends NativePeer {
      constructor(config?: RTCConfiguration) {
        super(forceRelay ? { ...config, iceTransportPolicy: "relay" } : config);
        window.__r5.peers.push(this);
        this.addEventListener("track", ({ track }) => window.__r5.tracks.push(track));
      }
    };
    const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await getUserMedia(constraints);
      window.__r5.tracks.push(...stream.getTracks());
      return stream;
    };
  }, relayOnly);
}

async function rtc(page: Page) {
  return page.evaluate(async () => {
    const peers = window.__r5.peers;
    const active = peers.filter((peer) => peer.connectionState !== "closed");
    let sent = 0, received = 0;
    const selected: { local: string; remote: string }[] = [];
    for (const peer of active) {
      const stats = await peer.getStats();
      stats.forEach((stat) => {
        if (stat.kind === "audio" || stat.mediaType === "audio") {
          if (stat.type === "outbound-rtp") sent += stat.bytesSent ?? 0;
          if (stat.type === "inbound-rtp") received += stat.bytesReceived ?? 0;
        }
        if (stat.type === "transport" && stat.selectedCandidatePairId) {
          const pair = stats.get(stat.selectedCandidatePairId);
          if (pair?.state === "succeeded") selected.push({
            local: stats.get(pair.localCandidateId)?.candidateType ?? "missing",
            remote: stats.get(pair.remoteCandidateId)?.candidateType ?? "missing",
          });
        }
      });
    }
    const senders = active.flatMap((peer) => peer.getSenders().flatMap((s) => s.track ? [s.track] : []));
    const receivers = active.flatMap((peer) => peer.getReceivers().map((r) => r.track));
    const audio = document.querySelector<HTMLAudioElement>("audio[aria-label]");
    return {
      total: peers.length,
      active: active.length,
      connected: active.length > 0 && active.every((p) => p.connectionState === "connected"),
      sent, received, selected,
      sending: senders.some((t) => t.kind === "audio" && t.readyState === "live" && t.enabled),
      muted: senders.length > 0 && senders.every((t) => !t.enabled),
      receiving: receivers.some((t) => t.kind === "audio" && t.readyState === "live"),
      playing: !!audio && !audio.paused && audio.srcObject instanceof MediaStream &&
        audio.srcObject.getAudioTracks().some((t) => t.readyState === "live"),
      stopped: window.__r5.tracks.length > 0 && window.__r5.tracks.every((t) => t.readyState === "ended"),
    };
  });
}

async function flowing(pages: Page[]): Promise<void> {
  for (const page of pages) {
    await expect.poll(async () => {
      const s = await rtc(page);
      return s.connected && s.sending && s.receiving && s.playing && s.sent > 0 && s.received > 0;
    }, { timeout: 30_000, message: "live audio tracks, playback and bidirectional RTP" }).toBe(true);
    if (relayOnly) {
      await expect.poll(async () => (await rtc(page)).selected, {
        timeout: 15_000, message: "selected local AND remote ICE candidates must be relay",
      }).toEqual([{ local: "relay", remote: "relay" }]);
    }
  }
  const before = await Promise.all(pages.map(rtc));
  await expect.poll(async () => {
    const after = await Promise.all(pages.map(rtc));
    return after.every((s, i) => s.sent > before[i]!.sent && s.received > before[i]!.received);
  }, { timeout: 15_000, message: "RTP bytes continue increasing in both directions" }).toBe(true);
}

for (const ending of ["guest leaves", "host ends"] as const) {
  test(`R5 ${relayOnly ? "relay-only" : "default ICE"}: audio, mute, reload, ${ending}`, async ({ browser, request }) => {
    test.setTimeout(150_000);
    const token = process.env.MOSAIQUE_HOST_TOKEN;
    expect(token, "MOSAIQUE_HOST_TOKEN must be seeded by the environment owner").toBeTruthy();
    const headers = { Authorization: `Bearer ${token}` };
    const created = await request.post("/api/meetings", { headers, data: { title: `R5 voice ${ending}` } });
    expect(created.ok()).toBeTruthy();
    const { meeting, invite_url: invite } = await created.json();
    const contexts: BrowserContext[] = [];
    try {
      for (let i = 0; i < 2; i++) {
        const context = await browser.newContext({
          baseURL: process.env.MOSAIQUE_BASE_URL ?? "http://localhost:5173", permissions: ["microphone"],
        });
        contexts.push(context);
        await observeRTC(context);
      }
      await contexts[0]!.addInitScript((value) => localStorage.setItem("mosaique.host_token", value), token!);
      const host = await contexts[0]!.newPage(), guest = await contexts[1]!.newPage();
      for (const [page, name] of [[host, "R5 Host"], [guest, "R5 Guest"]] as const) {
        await page.goto(invite);
        await page.getByLabel("Votre nom").fill(name);
        await page.getByRole("button", { name: /Rejoindre/ }).click();
        await expect(page).toHaveURL(new RegExp(`/meeting/${meeting.id}$`));
      }
      await flowing([host, guest]);
      for (const page of [host, guest]) {
        await page.getByRole("button", { name: "Couper le micro", exact: true }).click();
        await expect.poll(async () => (await rtc(page)).muted).toBe(true);
        // Muted RTP may still carry silence/comfort noise; zero bytes is not a mute contract.
        await page.getByRole("button", { name: "Réactiver le micro", exact: true }).click();
        await expect.poll(async () => (await rtc(page)).sending).toBe(true);
      }
      await flowing([host, guest]);
      const identity = () => guest.evaluate((id) =>
        JSON.parse(sessionStorage.getItem(`mosaique.meeting.${id}`)!).joined.participant.id, meeting.id);
      const beforeId = await identity();
      const hostPeerCount = (await rtc(host)).total;
      await guest.reload();
      await expect(guest.getByRole("button", { name: "Quitter", exact: true })).toBeVisible();
      expect(await identity()).toBe(beforeId);
      await expect.poll(async () => (await rtc(host)).total).toBeGreaterThan(hostPeerCount);
      await flowing([host, guest]);
      for (const page of [host, guest]) await expect(page.locator(".roster-entry")).toHaveCount(2);
      const detail = await request.get(`/api/meetings/${meeting.id}`, { headers });
      expect(detail.ok()).toBeTruthy();
      expect((await detail.json()).participants).toHaveLength(2);

      if (ending === "guest leaves") {
        await guest.getByRole("button", { name: "Quitter", exact: true }).click();
        await expect.poll(async () => {
          const s = await rtc(guest); return s.active === 0 && s.stopped;
        }).toBe(true);
        await expect.poll(async () => (await rtc(host)).active, { timeout: 20_000 }).toBe(0);
      }
      await host.getByRole("button", { name: "Terminer la réunion", exact: true }).click();
      for (const page of ending === "host ends" ? [host, guest] : [host]) {
        await expect(page.getByRole("heading", { name: "Compte rendu" })).toBeVisible({ timeout: 30_000 });
        await expect.poll(async () => {
          const s = await rtc(page); return s.active === 0 && s.stopped;
        }, { message: "all retained microphone/receiver tracks ended and peers closed" }).toBe(true);
      }
    } catch (error) {
      for (const context of contexts) for (const page of context.pages()) {
        console.log("R5 diagnostics", await rtc(page), await page.locator(".notice").allTextContents());
      }
      throw error;
    } finally {
      await Promise.all(contexts.map((context) => context.close()));
    }
  });
}
