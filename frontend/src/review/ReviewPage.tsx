import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type OutputsResponse, type TranscriptResponse } from "../api/client";
import { SessionPlayer } from "../audio/playback";
import {
  formatTimestamp,
  indexTranscript,
  resolveAll,
  unplayableCitations,
  type EvidenceTarget,
} from "./evidence";
import { resultSummary, splitOnMatches } from "./highlight";

/** Post-meeting review. Outputs are derived data; the transcript is authoritative. */
export function ReviewPage({ meetingId, onBack }: { meetingId: string; onBack: () => void }) {
  const [transcript, setTranscript] = useState<TranscriptResponse | null>(null);
  const [outputs, setOutputs] = useState<OutputsResponse | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  // What is typed, and what the server has actually answered for. Kept apart so
  // the transcript never renders under a heading describing a different query.
  const [queryInput, setQueryInput] = useState("");
  const [results, setResults] = useState<TranscriptResponse | null>(null);

  // One AudioContext for the page, one player per audio session. Created
  // lazily: browsers refuse to start a context before a user gesture, so
  // constructing it on mount would leave it permanently suspended.
  const contextRef = useRef<AudioContext | null>(null);
  const playersRef = useRef<Map<string, SessionPlayer>>(new Map());
  const segmentRefs = useRef<Map<string, HTMLParagraphElement>>(new Map());

  useEffect(() => {
    void api.transcript(meetingId).then(setTranscript);
  }, [meetingId]);

  // Debounced, and every response checked against the query still in the box:
  // without that, a slow answer for "bud" can land after a fast one for
  // "budget" and quietly show the wrong results.
  useEffect(() => {
    const wanted = queryInput.trim();
    if (!wanted) {
      setResults(null);
      return;
    }
    let cancelled = false;
    const handle = window.setTimeout(() => {
      void api
        .transcript(meetingId, wanted)
        .then((next) => {
          if (!cancelled && next.query === wanted) setResults(next);
        })
        .catch(() => {
          if (!cancelled) setResults(null);
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [meetingId, queryInput]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      if (cancelled) return;
      try {
        const next = await api.outputs(meetingId);
        if (cancelled) return;
        setOutputs(next);
        if (next.status !== "succeeded" && next.status !== "failed") {
          window.setTimeout(() => void poll(), 2000);
        }
      } catch {
        if (!cancelled) window.setTimeout(() => void poll(), 4000);
      }
    };
    void poll();
    return () => {
      cancelled = true;
    };
  }, [meetingId]);

  // Stop audio when the page goes away; a source node outlives React otherwise.
  useEffect(() => {
    const players = playersRef.current;
    const context = contextRef.current;
    return () => {
      players.forEach((player) => player.stop());
      void context?.close();
    };
  }, []);

  const index = useMemo(() => indexTranscript(transcript), [transcript]);

  const play = useCallback(
    async (target: EvidenceTarget) => {
      setActive(target.segmentId);
      setAudioError(null);

      // Scroll first: it is the half of FR-11 that works even with no audio.
      segmentRefs.current.get(target.segmentId)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });

      if (!target.audioSessionId || target.sessionMs === null) return;

      try {
        contextRef.current ??= new AudioContext();
        const context = contextRef.current;
        if (context.state === "suspended") await context.resume();

        let player = playersRef.current.get(target.audioSessionId);
        if (!player) {
          const sessionId = target.audioSessionId;
          const epochMs = index.sessions.get(sessionId)?.epoch_ms ?? 0;
          player = new SessionPlayer(
            sessionId,
            () => api.audio(meetingId, sessionId),
            epochMs,
          );
          playersRef.current.set(sessionId, player);
        }
        // Only one recording plays at a time; two participants at once is
        // noise, not review.
        playersRef.current.forEach((other) => other !== player && other.stop());

        await player.load(context);
        player.playFrom(target.meetingMs);
      } catch {
        setAudioError("L'enregistrement n'est pas disponible pour ce passage.");
      }
    },
    [index, meetingId],
  );

  const decisions = outputs?.decisions ?? [];
  const actions = outputs?.action_items ?? [];
  const unplayable = useMemo(() => unplayableCitations(outputs, index), [outputs, index]);

  // While a search is active the transcript shows the server's filtered list;
  // otherwise the whole thing. Citations always resolve against the *full*
  // transcript, so clicking a decision still works mid-search.
  const searching = results !== null;
  const shownSegments = searching ? results.segments : (transcript?.segments ?? []);
  const summary = searching
    ? resultSummary(results.segments.length, results.total_segments ?? 0, results.query ?? "")
    : "";
  const spansBySegment = useMemo(() => {
    const map = new Map<string, [number, number][]>();
    for (const match of results?.matches ?? []) {
      map.set(match.segment_id, match.spans as [number, number][]);
    }
    return map;
  }, [results]);
  const spansFor = (segmentId: string) => spansBySegment.get(segmentId);

  const evidence = (ids: string[]) => {
    const targets = resolveAll(ids, index);
    if (targets.length === 0) return null;
    return (
      <span className="evidence">
        {targets.map((target) => (
          <button
            key={target.segmentId}
            type="button"
            className="evidence-link"
            onClick={() => void play(target)}
            disabled={!target.audioSessionId}
            title={
              target.audioSessionId
                ? `${target.speaker} — ${target.text}`
                : "Aucun enregistrement pour ce passage"
            }
          >
            {formatTimestamp(target.meetingMs)}
          </button>
        ))}
      </span>
    );
  };

  return (
    <>
      <div className="head">
        <div>
          <h2>Compte rendu</h2>
          <p>Réunion terminée. Le transcript est enregistré.</p>
        </div>
        <button className="btn-quiet" onClick={onBack}>
          Retour aux réunions
        </button>
      </div>

      {audioError && (
        <div className="notice" role="status">
          {audioError}
        </div>
      )}

      {!outputs || (outputs.status !== "succeeded" && outputs.status !== "failed") ? (
        <div className="empty">
          <strong>Préparation du compte rendu…</strong>
          Le transcript ci-dessous est déjà enregistré.
        </div>
      ) : outputs.status === "failed" ? (
        <div className="notice" role="alert">
          Le compte rendu n'a pas pu être généré. Le transcript reste disponible.
        </div>
      ) : (
        <section className="outputs">
          <h3>Résumé</h3>
          <p>{outputs.summary}</p>

          {decisions.length > 0 && (
            <>
              <h3>Décisions</h3>
              <ul>
                {decisions.map((d, i) => (
                  <li key={i}>
                    {d.text}
                    {evidence(d.evidence_segment_ids)}
                  </li>
                ))}
              </ul>
            </>
          )}

          {actions.length > 0 && (
            <>
              <h3>Actions</h3>
              <ul>
                {actions.map((a, i) => (
                  <li key={i}>
                    {a.text}
                    {a.owner_text && <span className="owner">{a.owner_text}</span>}
                    {a.due_text && <span className="due">{a.due_text}</span>}
                    {evidence(a.evidence_segment_ids)}
                  </li>
                ))}
              </ul>
            </>
          )}

          {unplayable > 0 && (
            <p className="muted">
              {unplayable} extrait(s) sans enregistrement disponible.
            </p>
          )}
        </section>
      )}

      <h3 className="transcript-heading">Transcript</h3>

      <div className="transcript-search">
        <input
          type="search"
          value={queryInput}
          onChange={(event) => setQueryInput(event.target.value)}
          placeholder="Rechercher dans le transcript…"
          aria-label="Rechercher dans le transcript"
        />
        {summary && <span className="muted">{summary}</span>}
      </div>

      <div className="transcript">
        {shownSegments.map((segment) => (
          <p
            key={segment.id}
            ref={(node) => {
              if (node) segmentRefs.current.set(segment.id, node);
              else segmentRefs.current.delete(segment.id);
            }}
            className={`line line-final${active === segment.id ? " line-cited" : ""}`}
          >
            <span className="speaker">{index.speakerFor(segment.participant_id)}</span>
            {splitOnMatches(segment.text, spansFor(segment.id)).map((part, i) =>
              part.match ? (
                <mark key={i}>{part.text}</mark>
              ) : (
                <span key={i}>{part.text}</span>
              ),
            )}
          </p>
        ))}
      </div>
    </>
  );
}
