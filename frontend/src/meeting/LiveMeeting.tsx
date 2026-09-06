import { useCallback, useEffect, useRef, useState } from "react";
import { api, type JoinResponse } from "../api/client";
import { MicrophoneCapture } from "../audio/capture";
import { MeetingClient, type ConnectionState } from "../realtime/client";
import { TranscriptReconciler, type TranscriptEntry } from "../realtime/reconciler";
import { ParticipantRoster, type RosterEntry } from "../realtime/roster";
import { ParticipantPanel } from "./ParticipantPanel";

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  connecting: "Connexion…",
  live: "Transcription en cours",
  closed: "Déconnecté",
  error: "Transcription indisponible",
};

export function LiveMeeting({
  joined,
  isHost,
  onEnded,
}: {
  joined: JoinResponse;
  isHost: boolean;
  onEnded: () => void;
}) {
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const [participants, setParticipants] = useState<RosterEntry[]>([]);
  const [selfId, setSelfId] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [level, setLevel] = useState(0);
  const [micError, setMicError] = useState<string | null>(null);
  const [ending, setEnding] = useState(false);

  const reconciler = useRef(new TranscriptReconciler());
  const roster = useRef(new ParticipantRoster());
  const client = useRef<MeetingClient | null>(null);
  const capture = useRef<MicrophoneCapture | null>(null);

  const meetingId = joined.meeting.id;
  const sessionToken = joined.session_token;

  useEffect(() => {
    const meetingClient = new MeetingClient(meetingId, sessionToken, {
      onTranscript: (message) => {
        if (reconciler.current.apply(message)) setEntries(reconciler.current.ordered());
      },
      onRoster: (message) => {
        if (roster.current.apply(message)) setParticipants(roster.current.ordered());
      },
      onHelloOk: (participantId) => {
        setSelfId(participantId);
        const mic = new MicrophoneCapture();
        capture.current = mic;
        mic
          .start({
            onFrame: (pcm) => meetingClient.sendAudio(pcm),
            onLevel: setLevel,
          })
          .catch(() =>
            setMicError(
              "Micro refusé ou indisponible. Autorisez l'accès puis rechargez la page.",
            ),
          );
      },
      onMeetingState: (state) => {
        if (state === "COMPLETED") onEnded();
      },
      onConnectionState: setConnection,
      onError: (code, message) => setMicError(`${code} — ${message}`),
    });
    client.current = meetingClient;
    meetingClient.connect();

    return () => {
      void capture.current?.stop();
      meetingClient.close();
    };
  }, [meetingId, sessionToken, onEnded]);

  const end = useCallback(async () => {
    setEnding(true);
    await capture.current?.stop();
    try {
      await api.endMeeting(meetingId);
      onEnded();
    } finally {
      setEnding(false);
    }
  }, [meetingId, onEnded]);

  return (
    <>
      <div className="head">
        <div>
          <h2>{joined.meeting.title}</h2>
          <p>{joined.participant.display_name}</p>
        </div>
        {isHost && (
          <button className="btn-quiet" onClick={() => void end()} disabled={ending}>
            {ending ? "Finalisation…" : "Terminer la réunion"}
          </button>
        )}
      </div>

      <ParticipantPanel entries={participants} selfId={selfId} />

      <div className="statusbar">
        <span className="state">
          <span className="tessera" data-state={connection === "live" ? "LIVE" : ""} />
          {CONNECTION_LABEL[connection]}
        </span>
        <span className="meter" aria-label="Niveau du micro">
          <span className="meter-fill" style={{ width: `${Math.min(100, level * 180)}%` }} />
        </span>
      </div>

      {micError && (
        <div className="notice" role="alert">
          {micError}
        </div>
      )}

      {entries.length === 0 ? (
        <div className="empty">
          <strong>En écoute</strong>
          Le transcript apparaîtra ici dès que vous parlerez.
        </div>
      ) : (
        <div className="transcript">
          {entries.map((entry) => (
            <p key={entry.key} className={`line line-${entry.status}`}>
              <span className="speaker">{roster.current.nameFor(entry.participantId)}</span>
              {entry.text}
            </p>
          ))}
        </div>
      )}
    </>
  );
}
