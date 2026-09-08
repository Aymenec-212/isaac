/**
 * Turning `/readyz` into something worth showing a person (tech spec 15).
 *
 * The endpoint answers precisely — three dependencies, four states, a flag for
 * whether each gates readiness. A banner cannot say all of that without becoming
 * noise, so this module decides what is worth interrupting someone for.
 *
 * The rule: **say what they cannot do, and which thing to go fix.** "Service
 * dégradé" tells a person nothing they can act on; "la transcription est
 * indisponible" plus the dependency name tells them whether to restart the
 * model or the database.
 */

import type { DependencyView, ReadinessResponse } from "../api/client";

export type Severity = "ok" | "warning" | "blocked" | "unreachable";

export interface HealthBanner {
  severity: Severity;
  /** One sentence, in French, saying what is wrong in product terms. */
  message: string;
  /** Which dependencies to name. Empty when everything is fine. */
  culprits: string[];
  /** Whether starting a meeting now would be a bad idea. */
  canStartMeeting: boolean;
}

const OK: HealthBanner = {
  severity: "ok",
  message: "",
  culprits: [],
  canStartMeeting: true,
};

/** What each dependency means to someone trying to hold a meeting. */
const CONSEQUENCE: Record<string, string> = {
  database:
    "Le serveur ne peut pas enregistrer de réunion : la base de données est injoignable.",
  asr_runtime:
    "La transcription en direct est indisponible : le moteur de reconnaissance n'est pas prêt.",
  llm_provider:
    "Le compte rendu automatique est indisponible. La réunion et le transcript fonctionnent normalement.",
};

function consequence(name: string): string {
  return CONSEQUENCE[name] ?? `Dépendance indisponible : ${name}.`;
}

/**
 * Reduce a readiness response to a banner.
 *
 * Gating dependencies win over non-gating ones: if both the database and the
 * LLM provider are down, the sentence to show is the one about not being able
 * to record — telling someone their summary will be late while the meeting
 * itself cannot start would be actively misleading.
 */
export function bannerFor(readiness: ReadinessResponse | null): HealthBanner {
  if (readiness === null) {
    return {
      severity: "unreachable",
      message: "Le serveur est injoignable.",
      culprits: [],
      canStartMeeting: false,
    };
  }

  const broken = (readiness.dependencies ?? []).filter(
    (d: DependencyView) => d.state !== "ok",
  );
  if (broken.length === 0) return OK;

  const gating = broken.filter((d) => d.gates_readiness);
  if (gating.length > 0) {
    return {
      severity: "blocked",
      message: gating.map((d) => consequence(d.name)).join(" "),
      culprits: gating.map((d) => d.name),
      canStartMeeting: false,
    };
  }

  // Only non-gating dependencies are unhappy: the meeting still works, so this
  // is information rather than an obstacle.
  return {
    severity: "warning",
    message: broken.map((d) => consequence(d.name)).join(" "),
    culprits: broken.map((d) => d.name),
    canStartMeeting: true,
  };
}

/**
 * The technical detail, for someone who is going to go and fix it.
 *
 * Kept apart from `message` on purpose: the sentence above is for a person who
 * wants to know whether to start their meeting, this is for the same person ten
 * seconds later when they have decided to debug it instead.
 */
export function diagnosticLines(readiness: ReadinessResponse | null): string[] {
  if (readiness === null) return [];
  return (readiness.dependencies ?? [])
    .filter((d) => d.state !== "ok")
    .map((d) => `${d.name} — ${d.state} : ${d.detail}`);
}

/**
 * How often to re-check, in ms.
 *
 * Slower when healthy: polling a working server every two seconds is pure
 * noise, while a person staring at a broken one wants it to clear quickly once
 * they have restarted whatever it was.
 */
export function pollIntervalMs(severity: Severity): number {
  return severity === "ok" ? 30_000 : 5_000;
}
