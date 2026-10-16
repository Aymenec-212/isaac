import type { components } from "./schema";
export type Account = components["schemas"]["AccountView"];
export type Workspace = components["schemas"]["WorkspaceView"];
export type Member = components["schemas"]["MemberView"];
export type Meeting = components["schemas"]["EnterpriseMeetingView"];

export class SessionError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

// The session cookie is HttpOnly. CSRF is held in memory and refreshed from /me.
export async function request<T>(
  path: string,
  csrf?: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  let result: Response;
  try {
    result = await fetch(`/api/saas${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new SessionError("Le serveur est injoignable. Réessayez.", 0);
  }
  if (!result.ok) {
    const error = (await result.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new SessionError(
      error?.error?.message ?? "La demande a échoué. Actualisez et réessayez.",
      result.status,
    );
  }
  return (await result.json()) as T;
}
