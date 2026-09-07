/**
 * The participant panel's state (Slice 2).
 *
 * Pure and synchronous for the same reason as the reconciler: it is the part
 * worth testing, and a socket is not needed to test it.
 *
 * Two rules that are less obvious than they look:
 *
 *  - a participant who leaves is kept, marked absent, rather than removed. The
 *    transcript still holds their segments, and a line with no name against it
 *    is worse than a line marked as someone who has gone;
 *  - the server replays the existing roster to a joining socket as ordinary
 *    `participant.joined` messages, so a late join and a live one are the same
 *    code path here. Applying one twice must therefore be harmless.
 */
export interface RosterEntry {
  participantId: string;
  displayName: string;
  present: boolean;
  speaking: boolean;
}

export interface ParticipantMessage {
  type: "participant.joined" | "participant.left";
  participant_id: string;
  display_name: string;
}

export interface SpeakingMessage {
  type: "participant.speaking";
  participant_id: string;
  speaking: boolean;
}

export type RosterMessage = ParticipantMessage | SpeakingMessage;

export const isRosterMessage = (message: { type: string }): message is RosterMessage =>
  message.type === "participant.joined" ||
  message.type === "participant.left" ||
  message.type === "participant.speaking";

export class ParticipantRoster {
  /** Insertion order is join order, which is the order the panel shows. */
  private entries = new Map<string, RosterEntry>();

  apply(message: RosterMessage): boolean {
    const existing = this.entries.get(message.participant_id);

    if (message.type === "participant.speaking") {
      // Speaking for someone we have never been told about would leave a
      // nameless row in the panel; drop it and wait for the join.
      if (!existing || existing.speaking === message.speaking) return false;
      this.entries.set(message.participant_id, { ...existing, speaking: message.speaking });
      return true;
    }

    const present = message.type === "participant.joined";
    if (existing && existing.present === present && existing.displayName === message.display_name) {
      return false;
    }
    this.entries.set(message.participant_id, {
      participantId: message.participant_id,
      displayName: message.display_name,
      present,
      speaking: present ? (existing?.speaking ?? false) : false,
    });
    return true;
  }

  /** The display name for a transcript line, even after the speaker leaves. */
  nameFor(participantId: string): string {
    return this.entries.get(participantId)?.displayName ?? "Participant";
  }

  ordered(): RosterEntry[] {
    return [...this.entries.values()];
  }

  clear(): void {
    this.entries.clear();
  }
}
