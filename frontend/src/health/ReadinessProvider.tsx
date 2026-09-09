import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type ReadinessResponse } from "../api/client";
import { bannerFor, pollIntervalMs } from "./status";

/**
 * One readiness poll for the whole app (tech spec 15).
 *
 * This exists because of a bug found by hand on 2026-09-09 and not by any test:
 * `HealthBanner` polled `/readyz` privately, computed `canStartMeeting`, and
 * kept the answer to itself. So with the ASR runtime down the banner correctly
 * said **Service indisponible** while **Nouvelle réunion** stayed clickable —
 * the app told you transcription was unavailable and then let you start a
 * meeting that could not transcribe.
 *
 * The fix is deliberately a *shared* source rather than a second poll in
 * `MeetingList`. Two independent polls can land at different moments, and the
 * failure that produces — a banner saying blocked above a button saying go — is
 * the same class of bug as the one being fixed here, just harder to see.
 *
 * `undefined` is a third state and it matters: it means the first check has not
 * come back. Neither consumer may treat it as "broken" — the banner would flash
 * on every page load, and the button would be disabled for the first half second
 * of every visit. Not knowing yet is not the same as knowing something is wrong.
 */
export type Readiness = ReadinessResponse | null | undefined;

const ReadinessContext = createContext<Readiness>(undefined);

export function ReadinessProvider({ children }: { children: ReactNode }) {
  const [readiness, setReadiness] = useState<Readiness>(undefined);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      let next: ReadinessResponse | null;
      try {
        next = await api.readiness();
      } catch {
        // Distinct from a dependency being down: nothing answered at all.
        next = null;
      }
      if (cancelled) return;
      setReadiness(next);
      timer.current = window.setTimeout(
        () => void check(),
        pollIntervalMs(bannerFor(next).severity),
      );
    };

    void check();
    return () => {
      cancelled = true;
      window.clearTimeout(timer.current);
    };
  }, []);

  return <ReadinessContext.Provider value={readiness}>{children}</ReadinessContext.Provider>;
}

/** The latest readiness, or `undefined` while the first check is in flight. */
export function useReadiness(): Readiness {
  return useContext(ReadinessContext);
}
