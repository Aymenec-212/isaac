import type { RosterEntry } from "../realtime/roster";

/**
 * Who is in the meeting, and who is talking (Slice 2).
 *
 * Speaking comes from the segmenter, not from a microphone level: the dot
 * means "this person's words are being transcribed", which is the thing a
 * participant actually needs to trust.
 */
export function ParticipantPanel({
  entries,
  selfId,
}: {
  entries: RosterEntry[];
  selfId: string | null;
}) {
  if (entries.length === 0) return null;

  return (
    <ul className="roster" aria-label="Participants">
      {entries.map((entry) => (
        <li
          key={entry.participantId}
          className="roster-entry"
          data-speaking={entry.speaking ? "true" : "false"}
          data-present={entry.present ? "true" : "false"}
        >
          <span className="tessera" data-state={entry.speaking ? "LIVE" : ""} />
          <span className="roster-name">{entry.displayName}</span>
          {entry.participantId === selfId && <span className="roster-tag">vous</span>}
          {!entry.present && <span className="roster-tag">parti·e</span>}
        </li>
      ))}
    </ul>
  );
}
