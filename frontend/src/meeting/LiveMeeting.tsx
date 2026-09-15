import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
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

const WAVEFORM_BARS = [
  0.28, 0.42, 0.62, 0.38, 0.76, 0.52, 0.9, 0.64, 0.42, 0.72, 0.5, 0.84,
  0.58, 0.36, 0.68, 0.46, 0.8, 0.56, 0.34, 0.64, 0.48, 0.74, 0.4, 0.3,
];

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
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;
  const mutedRef = useRef(false);
  const finishCapture = useRef<() => Promise<void>>(async () => {});

  const meetingId = joined.meeting.id;
  const sessionToken = joined.session_token;
  const voiceLevel = Math.min(1, level * 1.8);

  useEffect(() => {
    const audio = remoteAudio.current;
    if (!audio) return;
    audio.srcObject = remoteStream;
    if (remoteStream) {
      void audio.play().then(() => setPlaybackBlocked(false)).catch(() => setPlaybackBlocked(true));
    }
  }, [remoteStream]);

  useEffect(() => {
    let disposed = false;
    let localCapture: MicrophoneCapture | null = null;
    let stopping = false;
    const stopMedia = async () => {
      stopping = true;
      if (!disposed) setEnding(true);
      localVoice.close();
      const flushed = await localCapture?.finish();
      if (flushed === false && !disposed) setMicError("La dernière fraction audio n'a pas pu être envoyée.");
      if (!disposed) setLevel(0);
    };
    finishCapture.current = stopMedia;
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
      onHelloOk: (participantId, _resumed, connectionId) => {
        if (disposed || stopping) return;
        setSelfId(participantId);
        if (connectionId) localVoice.setConnection(participantId, connectionId);
        loadIce();
        meetingClient.setPaused(mutedRef.current);
        {
          // Tech spec 7.3: anything finalized while we were away is not coming
          // back over the socket, so ask for it. Duplicates are harmless — the
          // reconciler ignores anything that does not raise the revision.
          void api
            .transcript(meetingId)
            .then((body) => {
              if (disposed) return;
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
        // A reconnect past the grace also arrives with resume:false, and the
        // microphone from before is still running. Starting a second one would
        // double this participant's audio.
        if (localCapture !== null) return;
        const mic = new MicrophoneCapture();
        localCapture = mic;
        capture.current = mic;
        mic.setMuted(mutedRef.current);
        mic
          .start({
            onFrame: (pcm) => meetingClient.sendAudio(pcm),
            onStream: (stream) => { if (!disposed && !stopping) localVoice.setLocalStream(stream); },
            onLevel: (value) => {
              setLevel(value);
              if (silence.current.observe(value, Date.now())) setNoAudio(true);
              else if (value > 0.001) setNoAudio(false);
            },
          })
          .catch(() => {
            void mic.stop();
            if (!disposed) setMicError(
              "Micro refusé ou indisponible. Autorisez l'accès puis rechargez la page.",
            );
          });
      },
      onMeetingState: (state) => {
        if (state === "COMPLETED") { void stopMedia(); onEndedRef.current(); }
        if (state === "FAILED") {
          void stopMedia();
          meetingClient.close();
          setMicError("La finalisation a échoué. Le compte rendu est incomplet.");
        }
      },
      onConnectionState: setConnection,
      onSignal: (message) => { if (!stopping) void localVoice.handleSignal(message); },
      onPeers: (peers) => { if (!stopping) localVoice.setPeers(peers); },
      onEndRequested: stopMedia,
      onError: (code, message) => {
        if (code === "SESSION_REPLACED" || code === "MEETING_NOT_LIVE") {
          void stopMedia();
        }
        if (code === "MEETING_NOT_LIVE") {
          // End can seal ingress before this socket receives the completion
          // broadcast. Read authorized state instead of stranding the guest.
          void api.getMeeting(meetingId).then((meeting) => {
            if (["COMPLETED", "FINALIZING"].includes(meeting.state)) onEndedRef.current();
          }).catch(() => undefined);
        }
        setMicError(`${code} — ${message}`);
      },
    });
    const localVoice = new WebRTCVoice({
      sendSignal: (message) => meetingClient.sendSignal(message),
      onRemoteStream: setRemoteStream,
      onState: setVoiceState,
    });
    voice.current = localVoice;
    client.current = meetingClient;
    const loadIce = () => { void api.iceConfig(meetingId).then((config) => {
      if (disposed || stopping) return;
      localVoice.setIceServers(config.ice_servers.map((server) => ({
        urls: server.urls,
        ...(server.username ? { username: server.username } : {}),
        ...(server.credential ? { credential: server.credential } : {}),
      })), config.ice_transport_policy);
    }).catch(() => {
      if (disposed || stopping) return;
      localVoice.close();
      setMicError("Voix directe indisponible — la transcription peut continuer.");
    }); };
    meetingClient.connect();

    return () => {
      disposed = true;
      stopping = true;
      void localCapture?.stop();
      localVoice.close();
      capture.current = null;
      meetingClient.close();
    };
  }, [meetingId, sessionToken]);

  const end = useCallback(async () => {
    setEnding(true);
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
    mutedRef.current = next;
    capture.current?.setMuted(next);
    voice.current?.setMuted(next);
    client.current?.setPaused(next);
  }, [muted]);

  const leave = useCallback(async () => {
    setEnding(true);
    await finishCapture.current();
    await client.current?.flush();
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
        <button className="btn-quiet" disabled={ending} onClick={toggleMute}>{muted ? "Réactiver le micro" : "Couper le micro"}</button>
        <button className="btn-quiet" disabled={ending} onClick={() => void leave()}>Quitter</button>
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
          <span className="voice-wave" aria-hidden="true">
            {WAVEFORM_BARS.map((amplitude, index) => (
              <span
                key={index}
                style={{
                  "--bar-height": `${8 + amplitude * 20}px`,
                  "--bar-scale": `${0.35 + voiceLevel * (0.4 + amplitude * 0.25)}`,
                  "--bar-opacity": `${0.42 + voiceLevel * 0.58}`,
                } as CSSProperties}
              />
            ))}
          </span>
        </span>
        <span className="state">Voix : {voiceState === "connected" ? "connectée" : voiceState === "failed" ? "indisponible" : voiceState === "idle" ? "en attente" : "connexion…"}</span>
      </div>

      <audio className="remote-audio" ref={remoteAudio} autoPlay aria-label="Audio de l'autre participant" />
      {playbackBlocked && (
        <button className="btn-quiet playback-action" onClick={() => void remoteAudio.current?.play().then(() => setPlaybackBlocked(false))}>
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
