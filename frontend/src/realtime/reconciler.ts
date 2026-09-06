/**
 * Client-side transcript reconciliation (tech spec 7.3).
 *
 * The rules, and why each exists:
 *
 *  - the key is `(participant_id, sequence)`, never array position, because
 *    messages from different participants interleave arbitrarily;
 *  - a message applies only if its `revision` exceeds the stored one, so a
 *    duplicate or a late-arriving message is harmless rather than a rewind;
 *  - a final freezes its key: once a segment is committed, no later delta may
 *    reopen it.
 *
 * Pure and synchronous, so it is unit-tested without a socket or a browser.
 */
export type SegmentStatus = "interim" | "final";

export interface TranscriptEntry {
  key: string;
  participantId: string;
  sequence: number;
  revision: number;
  status: SegmentStatus;
  text: string;
  startMs: number;
  endMs?: number;
  segmentId?: string;
}

export interface DeltaMessage {
  type: "transcript.delta";
  participant_id: string;
  sequence: number;
  revision: number;
  text: string;
  start_ms: number;
}

export interface FinalMessage {
  type: "transcript.segment.final";
  participant_id: string;
  sequence: number;
  revision: number;
  segment_id: string;
  text: string;
  start_ms: number;
  end_ms: number;
}

export type TranscriptMessage = DeltaMessage | FinalMessage;

export const keyOf = (participantId: string, sequence: number) => `${participantId}:${sequence}`;

export class TranscriptReconciler {
  private entries = new Map<string, TranscriptEntry>();

  apply(message: TranscriptMessage): boolean {
    const key = keyOf(message.participant_id, message.sequence);
    const existing = this.entries.get(key);

    if (existing?.status === "final") return false;
    if (existing && message.revision <= existing.revision) return false;

    this.entries.set(key, {
      key,
      participantId: message.participant_id,
      sequence: message.sequence,
      revision: message.revision,
      status: message.type === "transcript.segment.final" ? "final" : "interim",
      text: message.text,
      startMs: message.start_ms,
      endMs: message.type === "transcript.segment.final" ? message.end_ms : undefined,
      segmentId: message.type === "transcript.segment.final" ? message.segment_id : undefined,
    });
    return true;
  }

  /** Backfill after a reconnect. Server-stored finals always win. */
  hydrate(segments: FinalMessage[]): void {
    for (const segment of segments) this.apply(segment);
  }

  /** Display order: across participants by start time (tech spec 4).
   *
   * `participantId` breaks a tie before `sequence` does, matching the order
   * `GET /transcript` returns. Two participants can share a `startMs` — their
   * streams are anchored independently — and without a stable tiebreak the
   * hydrated view and the live view could disagree about which came first.
   */
  ordered(): TranscriptEntry[] {
    return [...this.entries.values()].sort(
      (a, b) =>
        a.startMs - b.startMs ||
        a.participantId.localeCompare(b.participantId) ||
        a.sequence - b.sequence,
    );
  }

  clear(): void {
    this.entries.clear();
  }
}
