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
import { groupIntoParagraphs } from "./paragraphs";

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

  // Slice 6R item 7. Which segment is open for editing, and what is in the box.
  // Deliberately one at a time: a transcript full of open editors is a form,
  // not a document.
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [draftSpeaker, setDraftSpeaker] = useState("");
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  // One AudioContext for the page, one player per audio session. Created
  // lazily: browsers refuse to start a context before a user gesture, so
  // constructing it on mount would leave it permanently suspended.
  const contextRef = useRef<AudioContext | null>(null);
  const playersRef = useRef<Map<string, SessionPlayer>>(new Map());
  const segmentRefs = useRef<Map<string, HTMLElement>>(new Map());

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

  const openEditor = useCallback(
    (segment: TranscriptResponse["segments"][number]) => {
      setEditing(segment.id);
      setDraft(segment.text);
      setDraftSpeaker(segment.participant_id);
      setEditError(null);
    },
    [],
  );

  const saveCorrection = useCallback(
    async (segmentId: string, originalText: string, originalSpeaker: string) => {
      const text = draft.trim();
      const body: { text?: string; participant_id?: string } = {};
      if (text && text !== originalText) body.text = text;
      if (draftSpeaker && draftSpeaker !== originalSpeaker) body.participant_id = draftSpeaker;
      // Nothing actually changed: closing is the honest outcome, and it saves a
      // round trip the server would reject anyway.
      if (!body.text && !body.participant_id) {
        setEditing(null);
        return;
      }

      setSaving(true);
      setEditError(null);
      try {
        await api.correctSegment(meetingId, segmentId, body);
        // Re-fetch rather than patching state in place: the correction also
        // moved the meeting's transcript version, and the outputs banner reads
        // that. Two sources of truth here is how they drift.
        const [nextTranscript, nextOutputs] = await Promise.all([
          api.transcript(meetingId),
          api.outputs(meetingId).catch(() => null),
        ]);
        setTranscript(nextTranscript);
        if (nextOutputs) setOutputs(nextOutputs);
        setEditing(null);
      } catch {
        setEditError("La correction n'a pas pu être enregistrée.");
      } finally {
        setSaving(false);
      }
    },
    [draft, draftSpeaker, meetingId],
  );

  const regenerate = useCallback(async () => {
    setRegenerating(true);
    try {
      await api.regenerateOutputs(meetingId);
      // The job is queued, not done — but unlike the first summary, a succeeded
      // one is already sitting there. Polling on `status` alone therefore
      // returns instantly with the *stale* outputs and calls it finished; the
      // browser test caught exactly that. The condition that means "caught up"
      // is the version handshake, not the status.
      const poll = async (attempt = 0): Promise<void> => {
        const next = await api.outputs(meetingId);
        setOutputs(next);
        const caughtUp =
          next.generated_from_transcript_version != null &&
          next.current_transcript_version != null &&
          next.generated_from_transcript_version >= next.current_transcript_version;
        // Give up quietly after ~30 s: the banner still says the summary needs
        // review, which is true, and the button can be pressed again.
        if (caughtUp || next.status === "failed" || attempt >= 15) return;
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        return poll(attempt + 1);
      };
      await poll();
    } catch {
      setEditError("La régénération n'a pas pu être lancée.");
    } finally {
      setRegenerating(false);
    }
  }, [meetingId]);

  // The two numbers the server hands back. Different means the transcript has
  // been corrected since these insights were derived from it.
  const outputsStale =
    outputs?.status === "succeeded" &&
    outputs.generated_from_transcript_version != null &&
    outputs.current_transcript_version != null &&
    outputs.generated_from_transcript_version < outputs.current_transcript_version;

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
  // Succeeded, but with nothing extracted. Distinct from "failed" and from
  // "still running", and previously indistinguishable from either: the page
  // simply rendered a summary with no headings under it.
  const thinOutputs =
    outputs?.status === "succeeded" && decisions.length === 0 && actions.length === 0;
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

  // Slice 6R: read as paragraphs, not as one line per model event. Applied to
  // the filtered list too, and that needs no special case — search hits are far
  // apart in time, so the pause rule already gives each its own block.
  const paragraphs = useMemo(() => groupIntoParagraphs(shownSegments), [shownSegments]);

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
          <strong>Le compte rendu n'a pas pu être généré.</strong>
          <div>
            Le transcript ci-dessous est complet et enregistré : c'est la seule
            partie qui fait foi. Seul le résumé automatique manque.
          </div>
          {outputs.error_code && <code>Référence : {outputs.error_code}</code>}
        </div>
      ) : (
        <section className="outputs">
          {/* Item 7's provenance line. Always shown, so "generated from v1" is
              ordinary rather than an alarm — and when the transcript has moved
              on, the same line is what says so. */}
          <div className={`outputs-provenance${outputsStale ? " outputs-stale" : ""}`} role="status">
            <span>
              Compte rendu généré à partir du transcript v
              {outputs.generated_from_transcript_version ?? 1}
            </span>
            {outputsStale && (
              <>
                <strong>Le transcript a été corrigé — le compte rendu est à revoir.</strong>
                <button
                  type="button"
                  className="btn-quiet"
                  onClick={() => void regenerate()}
                  disabled={regenerating}
                >
                  {regenerating ? "Régénération…" : "Régénérer le compte rendu"}
                </button>
              </>
            )}
          </div>

          {thinOutputs && (
            <div className="notice" role="status">
              <strong>Compte rendu partiel.</strong>
              <div>
                Le modèle n'a extrait ni décision ni action de cette réunion. Cela
                arrive sur une réunion courte ou peu structurée — le résumé et le
                transcript restent utilisables.
              </div>
            </div>
          )}

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
        {paragraphs.map((paragraph) => (
          <article key={paragraph.key} className="para">
            {/* Said once per paragraph rather than once per segment. That single
                change is most of what turns ~930 labelled lines into a readable
                hour. */}
            <header className="para-head">
              <span className="speaker">{index.speakerFor(paragraph.participantId)}</span>
              <span className="para-time">{formatTimestamp(paragraph.startMs)}</span>
            </header>
            {/* The editor replaces nothing: it sits under the paragraph that
                holds the segment, so the surrounding words stay readable while
                someone fixes one of them. */}
            {paragraph.segments.some((segment) => segment.id === editing) && (
              <div className="seg-editor">
                <label>
                  Texte
                  <textarea
                    value={draft}
                    rows={2}
                    aria-label="Texte du segment"
                    onChange={(event) => setDraft(event.target.value)}
                  />
                </label>
                <label>
                  Intervenant
                  <select
                    value={draftSpeaker}
                    aria-label="Intervenant du segment"
                    onChange={(event) => setDraftSpeaker(event.target.value)}
                  >
                    {(transcript?.participants ?? []).map((participant) => (
                      <option key={participant.id} value={participant.id}>
                        {participant.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="seg-editor-actions">
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={saving}
                    onClick={() => {
                      const segment = paragraph.segments.find((x) => x.id === editing);
                      if (segment) {
                        void saveCorrection(segment.id, segment.text, segment.participant_id);
                      }
                    }}
                  >
                    {saving ? "Enregistrement…" : "Enregistrer"}
                  </button>
                  <button type="button" className="btn-quiet" onClick={() => setEditing(null)}>
                    Annuler
                  </button>
                </div>
                {editError && (
                  <p className="field-note" role="alert">
                    {editError}
                  </p>
                )}
                <p className="muted">
                  La transcription d'origine est conservée : une correction ne
                  l'efface pas.
                </p>
              </div>
            )}

            <p className="para-body line-final">
              {paragraph.segments.map((segment) => (
                // One element per segment, still. Grouping changes how the
                // transcript looks and never what is addressable: a citation
                // scrolls to this node and a highlight indexes into this
                // segment's own text at the server's offsets.
                <span
                  key={segment.id}
                  data-segment-id={segment.id}
                  ref={(node) => {
                    if (node) segmentRefs.current.set(segment.id, node);
                    else segmentRefs.current.delete(segment.id);
                  }}
                  className={
                    `seg${active === segment.id ? " seg-cited" : ""}` +
                    (segment.original_text || segment.original_participant_id
                      ? " seg-corrected"
                      : "")
                  }
                  title={
                    segment.original_text
                      ? `Texte d'origine : ${segment.original_text}`
                      : undefined
                  }
                  onDoubleClick={() => openEditor(segment)}
                >
                  {splitOnMatches(segment.text, spansFor(segment.id)).map((part, i) =>
                    part.match ? (
                      <mark key={i}>{part.text}</mark>
                    ) : (
                      <span key={i}>{part.text}</span>
                    ),
                  )}
                  {/* Small, always present rather than on hover: a control that
                      only exists on hover cannot be found by keyboard or touch. */}
                  <button
                    type="button"
                    className="seg-edit"
                    aria-label={`Corriger : ${segment.text.slice(0, 40)}`}
                    onClick={() => openEditor(segment)}
                  >
                    ✎
                  </button>{" "}
                </span>
              ))}
            </p>
          </article>
        ))}
      </div>
    </>
  );
}
