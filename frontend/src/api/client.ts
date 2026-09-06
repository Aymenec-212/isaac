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

export const api = {
  livez: () => request<{ status: string; version: string }>("/livez"),
  listMeetings: () => request<{ meetings: Meeting[] }>("/meetings"),
  getMeeting: (id: string) => request<MeetingDetail>(`/meetings/${id}`),
  createMeeting: (title: string) =>
    request<CreateMeetingResponse>("/meetings", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
};
