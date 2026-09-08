/**
 * Turning `evidence_segment_ids` into something a person can click (FR-11).
 *
 * The model cites segment ids. A reader wants to jump to the moment. Bridging
 * those is arithmetic over three facts — which segment, which recording, and
 * where that recording starts on the meeting timeline — and it is pure, so it
 * is here rather than inside a component.
 *
 * The rule that matters: **a citation that cannot be resolved is shown as
 * unplayable, never silently dropped.** The server has already rejected ids
 * that match no segment (`schema.py`), so anything unresolvable here is a
 * segment whose audio is missing — a gap segment (L-20), a null-store replay,
 * or a file Q3 retention removed. Hiding those would make a real citation look
 * like a model that failed to cite anything.
 */

import type { OutputsResponse, TranscriptResponse } from "../api/client";

type Segment = TranscriptResponse["segments"][number];
type AudioSession = NonNullable<TranscriptResponse["audio_sessions"]>[number];

export interface EvidenceTarget {
  segmentId: string;
  /** Meeting-relative, for scrolling and for the timestamp label. */
  meetingMs: number;
  text: string;
  speaker: string;
  /** Null when this moment has no stored audio; the citation still shows. */
  audioSessionId: string | null;
  /** Offset inside the recording, once the session epoch is subtracted. */
  sessionMs: number | null;
}

export interface TranscriptIndex {
  segments: Map<string, Segment>;
  sessions: Map<string, AudioSession>;
  speakerFor: (participantId: string) => string;
}

export function indexTranscript(transcript: TranscriptResponse | null): TranscriptIndex {
  const segments = new Map<string, Segment>();
  const sessions = new Map<string, AudioSession>();
  const names = new Map<string, string>();

  for (const segment of transcript?.segments ?? []) segments.set(segment.id, segment);
  for (const session of transcript?.audio_sessions ?? []) sessions.set(session.id, session);
  for (const participant of transcript?.participants ?? []) {
    names.set(participant.id, participant.display_name);
  }

  return {
    segments,
    sessions,
    speakerFor: (participantId) => names.get(participantId) ?? "Participant",
  };
}

/** Resolve one citation. Returns null only when the segment itself is unknown. */
export function resolveEvidence(
  segmentId: string,
  index: TranscriptIndex,
): EvidenceTarget | null {
  const segment = index.segments.get(segmentId);
  if (!segment) return null;

  const sessionId = segment.audio_session_id ?? null;
  const session = sessionId ? index.sessions.get(sessionId) : undefined;

  // Without the session's epoch the offset would be wrong rather than missing,
  // and a player that seeks to the wrong moment is worse than one that will
  // not seek at all.
  const sessionMs = session ? Math.max(0, segment.start_ms - session.epoch_ms) : null;

  return {
    segmentId,
    meetingMs: segment.start_ms,
    text: segment.text,
    speaker: index.speakerFor(segment.participant_id),
    audioSessionId: session ? session.id : null,
    sessionMs,
  };
}

/** Resolve every citation on one decision or action item, in transcript order. */
export function resolveAll(
  segmentIds: readonly string[],
  index: TranscriptIndex,
): EvidenceTarget[] {
  const targets = segmentIds
    .map((id) => resolveEvidence(id, index))
    .filter((t): t is EvidenceTarget => t !== null);

  return targets.sort((a, b) => a.meetingMs - b.meetingMs);
}

/** `mm:ss`, matching how the prompt showed the model the same moment. */
export function formatTimestamp(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

type EvidenceBacked = { text: string; evidence_segment_ids: string[] };

/**
 * Citations the server accepted but this client cannot play.
 *
 * Surfaced rather than counted quietly: it is the honest measure of how much
 * of a review page's evidence actually works, and the first symptom of audio
 * having been discarded or expired.
 */
export function unplayableCitations(
  outputs: OutputsResponse | null,
  index: TranscriptIndex,
): number {
  const items: EvidenceBacked[] = [
    ...(outputs?.decisions ?? []),
    ...(outputs?.action_items ?? []),
  ];

  let unplayable = 0;
  for (const item of items) {
    for (const id of item.evidence_segment_ids) {
      const target = resolveEvidence(id, index);
      if (!target || target.audioSessionId === null) unplayable += 1;
    }
  }
  return unplayable;
}
