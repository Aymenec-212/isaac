import { useCallback, useEffect, useRef, useState } from "react";
import { api, type JoinResponse } from "../api/client";
import { MicrophoneCapture } from "../audio/capture";
import {
  MeetingClient,
  type ConnectionState,
  type StreamState,
} from "../realtime/client";
import { SilenceWatcher } from "../realtime/silence";
import { TranscriptReconciler, type TranscriptEntry } from "../realtime/reconciler";
import { ParticipantRoster, type RosterEntry } from "../realtime/roster";
import { ParticipantPanel } from "./ParticipantPanel";

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  connecting: "Connexion…",
  live: "Transcription en cours",
  reconnecting: "Reconnexion…",
  closed: "Déconnecté",
  error: "Transcription indisponible",
};

/* The five states of tech spec 8.4. `unavailable` says plainly that the
   transcript has stopped while the recording has not, because that is the one
   case where a participant might otherwise stop talking for nothing. */
const STREAM_LABEL: Record<StreamState, string> = {
  listening: "Micro coupé",
  receiving: "Réception de l'audio…",
  transcribing: "Transcription en cours",
  delayed: "Transcription en retard",
  unavailable: "Transcription indisponible — l'audio est toujours enregistré",
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
  const [noAudio, setNoAudio] = useState(false);
  const [stream, setStream] = useState<StreamState | null>(null);
  const [lagMs, setLagMs] = useState(0);
  const [ending, setEnding] = useState(false);

  const reconciler = useRef(new TranscriptReconciler());
  const roster = useRef(new ParticipantRoster());
  const silence = useRef(new SilenceWatcher());
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
      onStreamStatus: (status, lag) => {
        setStream(status);
        setLagMs(lag);
      },
      onHelloOk: (participantId, resumed) => {
        setSelfId(participantId);
        if (resumed) {
          // Tech spec 7.3: anything finalized while we were away is not coming
          // back over the socket, so ask for it. Duplicates are harmless — the
          // reconciler ignores anything that does not raise the revision.
          void api
            .transcript(meetingId)
            .then((body) => {
              reconciler.current.hydrate(
                body.segments.map((segment) => ({
                  type: "transcript.segment.final" as const,
                  participant_id: segment.participant_id,
                  sequence: segment.sequence,
                  revision: 1,
                  segment_id: segment.id,
                  text: segment.text,
                  start_ms: segment.start_ms,
                  end_ms: segment.end_ms,
                })),
              );
              setEntries(reconciler.current.ordered());
            })
            .catch(() => undefined);
          return;
        }
        // A reconnect past the grace also arrives with resume:false, and the
        // microphone from before is still running. Starting a second one would
        // double this participant's audio.
        if (capture.current !== null) return;
        const mic = new MicrophoneCapture();
        capture.current = mic;
        mic
          .start({
            onFrame: (pcm) => meetingClient.sendAudio(pcm),
            onLevel: (value) => {
              setLevel(value);
              if (silence.current.observe(value, Date.now())) setNoAudio(true);
              else if (value > 0.001) setNoAudio(false);
            },
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
          {connection === "live" && stream
            ? STREAM_LABEL[stream] + (stream === "delayed" ? ` (${Math.round(lagMs / 100) / 10} s)` : "")
            : CONNECTION_LABEL[connection]}
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

      {noAudio && !micError && (
        <div className="notice" role="status">
          Aucun son détecté. Vérifiez que votre micro n'est pas coupé.
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
              {/* Slice 6R item 2. Interim text used to be marked by italics and a
                  grey border alone — invisible to anyone who cannot separate the
                  two colours, and easy to miss for everyone else. The word says
                  what the styling implies, so the distinction no longer depends
                  on seeing a hue. */}
              {entry.status === "interim" && (
                <span className="tag-interim" aria-label="transcription en cours">
                  en cours
                </span>
              )}
              {entry.text}
            </p>
          ))}
        </div>
      )}
    </>
  );
}
