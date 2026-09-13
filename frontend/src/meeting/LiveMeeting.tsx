import { useCallback, useEffect, useRef, useState } from "react";
import { api, type JoinResponse } from "../api/client";
import { MicrophoneCapture } from "../audio/capture";
import {
  MeetingClient,
  type ConnectionState,
  type StreamState,
} from "../realtime/client";
import { WebRTCVoice, type VoiceState } from "../realtime/webrtc";
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

/* Transcription state does not certify recording durability. Recording
   failures arrive separately as AUDIO_RECORDING_FAILED. */
const STREAM_LABEL: Record<StreamState, string> = {
  listening: "Micro coupé",
  receiving: "Réception de l'audio…",
  transcribing: "Transcription en cours",
  delayed: "Transcription en retard",
  unavailable: "Transcription indisponible — une partie du texte peut manquer",
};

export function LiveMeeting({
  joined,
  isHost,
  onEnded,
  onLeft,
}: {
  joined: JoinResponse;
  isHost: boolean;
  onEnded: () => void;
  onLeft: () => void;
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
  const [muted, setMuted] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const [playbackBlocked, setPlaybackBlocked] = useState(false);

  const reconciler = useRef(new TranscriptReconciler());
  const roster = useRef(new ParticipantRoster());
  const silence = useRef(new SilenceWatcher());
  const client = useRef<MeetingClient | null>(null);
  const capture = useRef<MicrophoneCapture | null>(null);
  const voice = useRef<WebRTCVoice | null>(null);
  const remoteAudio = useRef<HTMLAudioElement | null>(null);

  const meetingId = joined.meeting.id;
  const sessionToken = joined.session_token;

  useEffect(() => {
    const audio = remoteAudio.current;
    if (!audio) return;
    audio.srcObject = remoteStream;
    if (remoteStream) {
      void audio.play().then(() => setPlaybackBlocked(false)).catch(() => setPlaybackBlocked(true));
    }
  }, [remoteStream]);

  useEffect(() => {
    const meetingClient = new MeetingClient(meetingId, sessionToken, {
      onTranscript: (message) => {
        if (reconciler.current.apply(message)) setEntries(reconciler.current.ordered());
      },
      onRoster: (message) => {
        if (roster.current.apply(message)) setParticipants(roster.current.ordered());
        if (message.type === "participant.joined") voice.current?.participantJoined(message.participant_id);
        if (message.type === "participant.left") voice.current?.participantLeft(message.participant_id);
      },
      onStreamStatus: (status, lag) => {
        setStream(status);
        setLagMs(lag);
      },
      onHelloOk: (participantId, resumed) => {
        setSelfId(participantId);
        voice.current?.setSelfId(participantId);
        {
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
                  status: segment.status === "gap" ? "gap" as const : "final" as const,
                  text: segment.text,
                  start_ms: segment.start_ms,
                  end_ms: segment.end_ms,
                })),
              );
              setEntries(reconciler.current.ordered());
            })
            .catch(() => undefined);
        }
        if (resumed) return;
        // A reconnect past the grace also arrives with resume:false, and the
        // microphone from before is still running. Starting a second one would
        // double this participant's audio.
        if (capture.current !== null) return;
        const mic = new MicrophoneCapture();
        capture.current = mic;
        mic
          .start({
            onFrame: (pcm) => meetingClient.sendAudio(pcm),
            onStream: (stream) => voice.current?.setLocalStream(stream),
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
        if (state === "FAILED") {
          void capture.current?.stop();
          meetingClient.close();
          setMicError("La finalisation a échoué. Le compte rendu est incomplet.");
        }
      },
      onConnectionState: setConnection,
      onSignal: (message) => { void voice.current?.handleSignal(message); },
      onError: (code, message) => {
        if (code === "SESSION_REPLACED" || code === "MEETING_NOT_LIVE") {
          void capture.current?.stop();
        }
        if (code === "MEETING_NOT_LIVE") {
          // End can seal ingress before this socket receives the completion
          // broadcast. Read authorized state instead of stranding the guest.
          void api.getMeeting(meetingId).then((meeting) => {
            if (["COMPLETED", "FINALIZING"].includes(meeting.state)) onEnded();
          }).catch(() => undefined);
        }
        setMicError(`${code} — ${message}`);
      },
    });
    voice.current = new WebRTCVoice({
      sendSignal: (message) => meetingClient.sendSignal(message),
      onRemoteStream: setRemoteStream,
      onState: setVoiceState,
    });
    client.current = meetingClient;
    meetingClient.connect();
    void api.iceConfig(meetingId).then((config) => {
      voice.current?.setIceServers(config.ice_servers.map((server) => ({
        urls: server.urls,
        ...(server.username ? { username: server.username } : {}),
        ...(server.credential ? { credential: server.credential } : {}),
      })));
    }).catch(() => {
      voice.current?.setIceServers([]);
      setMicError("Voix directe indisponible — la transcription peut continuer.");
    });

    return () => {
      void capture.current?.stop();
      voice.current?.close();
      meetingClient.close();
    };
  }, [meetingId, sessionToken, onEnded]);

  const end = useCallback(async () => {
    setEnding(true);
    await client.current?.flush();
    await capture.current?.stop();
    voice.current?.close();
    try {
      await api.endMeeting(meetingId);
      onEnded();
    } catch {
      setMicError("La finalisation a échoué. Le compte rendu est incomplet.");
    } finally {
      setEnding(false);
    }
  }, [meetingId, onEnded]);

  const toggleMute = useCallback(() => {
    const next = !muted;
    setMuted(next);
    capture.current?.setMuted(next);
    voice.current?.setMuted(next);
    client.current?.setPaused(next);
  }, [muted]);

  const leave = useCallback(() => {
    void client.current?.flush();
    void capture.current?.stop();
    voice.current?.close();
    client.current?.close();
    onLeft();
  }, [onLeft]);

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
        <button className="btn-quiet" onClick={toggleMute}>{muted ? "Réactiver le micro" : "Couper le micro"}</button>
        <button className="btn-quiet" onClick={leave}>Quitter</button>
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
        <span className="state">Voix : {voiceState === "connected" ? "connectée" : voiceState === "failed" ? "indisponible" : voiceState === "idle" ? "en attente" : "connexion…"}</span>
      </div>

      <audio ref={remoteAudio} autoPlay controls aria-label="Audio de l'autre participant" />
      {playbackBlocked && (
        <button className="btn-quiet" onClick={() => void remoteAudio.current?.play().then(() => setPlaybackBlocked(false))}>
          Activer le son de l'autre participant
        </button>
      )}

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
