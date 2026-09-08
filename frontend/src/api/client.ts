/**
 * Typed API client.
 *
 * Types come from `schema.d.ts`, which is generated from the backend's own
 * OpenAPI document (`npm run generate:api`). A route that changes shape on the
 * server breaks the build here rather than at runtime in a meeting.
 */
import type { components } from "./schema";

export type Meeting = components["schemas"]["MeetingView"];
export type MeetingDetail = components["schemas"]["MeetingDetailView"];
export type CreateMeetingResponse = components["schemas"]["CreateMeetingResponse"];
export type ErrorEnvelope = components["schemas"]["ErrorEnvelope"];

const BASE = "/api";

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly requestId: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Where the host token lives until Slice 7 replaces it with magic-link login. */
const TOKEN_KEY = "mosaique.host_token";

export const token = {
  get: (): string | null => window.localStorage.getItem(TOKEN_KEY),
  set: (value: string) => window.localStorage.setItem(TOKEN_KEY, value),
  clear: () => window.localStorage.removeItem(TOKEN_KEY),
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const bearer = token.get();
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("NETWORK_UNAVAILABLE", "Le serveur est injoignable.", "", 0);
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ErrorEnvelope | null;
    throw new ApiError(
      body?.error.code ?? "INTERNAL_ERROR",
      body?.error.message ?? "Erreur inattendue.",
      body?.error.request_id ?? "",
      response.status,
    );
  }
  return (await response.json()) as T;
}

export type TranscriptResponse = components["schemas"]["TranscriptResponse"];
export type OutputsResponse = components["schemas"]["OutputsResponse"];
export type JoinResponse = components["schemas"]["JoinResponse"];
export type ReadinessResponse = components["schemas"]["ReadinessResponse"];
export type DependencyView = components["schemas"]["DependencyView"];

export const api = {
  livez: () => request<{ status: string; version: string }>("/livez"),

  /**
   * Which dependencies are up (tech spec 15).
   *
   * Not routed through `request`, because a 503 is the *expected* answer when
   * something is down and `request` would turn it into a thrown ApiError. The
   * body is the same shape either way and it is the body we want.
   *
   * No token: the health endpoints are the deliberate unauthenticated
   * exception, since a load balancer has no credentials and neither does
   * someone debugging a local run.
   */
  readiness: async (): Promise<ReadinessResponse> => {
    const response = await fetch(`${BASE}/readyz`);
    if (response.status !== 200 && response.status !== 503) {
      throw new ApiError("HEALTH_UNAVAILABLE", "État du serveur inconnu.", "", response.status);
    }
    return (await response.json()) as ReadinessResponse;
  },
  listMeetings: () => request<{ meetings: Meeting[] }>("/meetings"),
  getMeeting: (id: string) => request<MeetingDetail>(`/meetings/${id}`),
  createMeeting: (title: string) =>
    request<CreateMeetingResponse>("/meetings", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  join: (meetingId: string, displayName: string, inviteToken: string) =>
    request<JoinResponse>(`/meetings/${meetingId}/join`, {
      method: "POST",
      body: JSON.stringify({ display_name: displayName, invite_token: inviteToken }),
    }),
  endMeeting: (meetingId: string) =>
    request<{ meeting: Meeting }>(`/meetings/${meetingId}/end`, { method: "POST" }),
  transcript: (meetingId: string) =>
    request<TranscriptResponse>(`/meetings/${meetingId}/transcript`),
  outputs: (meetingId: string) => request<OutputsResponse>(`/meetings/${meetingId}/outputs`),

  /**
   * Stored PCM for one audio session (FR-11).
   *
   * Not routed through `request`: the body is raw bytes, not JSON, and the
   * Web Audio path wants an ArrayBuffer. The bearer token still travels,
   * because the route is tenant-scoped like every other read.
   */
  audio: async (meetingId: string, sessionId: string): Promise<ArrayBuffer> => {
    const headers = new Headers();
    const bearer = token.get();
    if (bearer) headers.set("Authorization", `Bearer ${bearer}`);

    let response: Response;
    try {
      response = await fetch(`${BASE}/meetings/${meetingId}/audio/${sessionId}`, { headers });
    } catch {
      throw new ApiError("NETWORK_UNAVAILABLE", "Le serveur est injoignable.", "", 0);
    }
    if (!response.ok) {
      throw new ApiError(
        "AUDIO_UNAVAILABLE",
        "L'enregistrement n'est pas disponible.",
        "",
        response.status,
      );
    }
    return response.arrayBuffer();
  },
};
