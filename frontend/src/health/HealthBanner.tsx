import { useEffect, useRef, useState } from "react";
import { api, type ReadinessResponse } from "../api/client";
import { bannerFor, diagnosticLines, pollIntervalMs } from "./status";

/**
 * Shows which dependency is broken, when one is (tech spec 15).
 *
 * Phase A's reason for existing: a person running meetings on their own machine
 * needs to know *before* they start talking that the transcription engine is
 * still loading — and afterwards, which of three things to go restart.
 *
 * Renders nothing when everything is fine. A permanent green badge is furniture;
 * this appears only when it has something to say.
 */
export function HealthBanner() {
  const [readiness, setReadiness] = useState<ReadinessResponse | null | undefined>(undefined);
  const [showDetail, setShowDetail] = useState(false);
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

  // `undefined` is "the first check has not come back". Showing "server
  // unreachable" for that half-second would be a lie every time the page loads.
  if (readiness === undefined) return null;

  const banner = bannerFor(readiness);
  if (banner.severity === "ok") return null;

  const detail = diagnosticLines(readiness);

  return (
    <div
      className={`health-banner health-${banner.severity}`}
      role={banner.canStartMeeting ? "status" : "alert"}
    >
      <div className="health-message">
        <strong>{banner.canStartMeeting ? "Service dégradé" : "Service indisponible"}</strong>
        <span>{banner.message}</span>
      </div>

      {detail.length > 0 && (
        <button
          type="button"
          className="btn-quiet health-toggle"
          onClick={() => setShowDetail((open) => !open)}
          aria-expanded={showDetail}
        >
          {showDetail ? "Masquer le détail" : "Détail technique"}
        </button>
      )}

      {showDetail && (
        <ul className="health-detail">
          {detail.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
