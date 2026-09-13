/** Tab-scoped participant identity and retry keys. Tokens are still checked by the server. */
import type { components } from "./schema";
type Joined = components["schemas"]["JoinResponse"];
const HOST_KEY = "mosaique.host_token";
const prefix = "mosaique.meeting.";
interface Saved { joined: Joined; hostToken: string | null }

export const token = {
  get: (): string | null => window.localStorage.getItem(HOST_KEY),
  set: (value: string) => window.localStorage.setItem(HOST_KEY, value),
  clear: () => window.localStorage.removeItem(HOST_KEY),
};

function saved(meetingId: string): Saved | null {
  try {
    const raw = window.sessionStorage.getItem(prefix + meetingId);
    if (!raw) return null;
    const value = JSON.parse(raw) as Saved;
    if (value.joined?.meeting?.id !== meetingId || !value.joined.session_token ||
        !value.joined.participant?.id) return null;
    return value;
  } catch { return null; }
}

export const meetingCredentials = {
  get: (meetingId: string): Joined | null => saved(meetingId)?.joined ?? null,
  save: (joined: Joined) => window.sessionStorage.setItem(prefix + joined.meeting.id,
    JSON.stringify({ joined, hostToken: joined.can_manage ? token.get() : null })),
  bearer: (meetingId: string): string | null => {
    const value = saved(meetingId);
    if (!value) return token.get();
    // An unrelated or subsequently changed host login must not replace a guest's credential.
    if (value.hostToken && value.hostToken === token.get()) return value.hostToken;
    return value.joined.session_token;
  },
  nonce: (meetingId: string): string => {
    const key = prefix + meetingId + ".nonce";
    let value = window.sessionStorage.getItem(key);
    if (!value) {
      value = crypto.randomUUID();
      window.sessionStorage.setItem(key, value);
    }
    return value;
  },
};
