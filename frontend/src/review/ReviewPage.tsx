import { useEffect, useState } from "react";
import { api, type OutputsResponse, type TranscriptResponse } from "../api/client";

/** Post-meeting review. Outputs are derived data; the transcript is authoritative. */
export function ReviewPage({ meetingId, onBack }: { meetingId: string; onBack: () => void }) {
  const [transcript, setTranscript] = useState<TranscriptResponse | null>(null);
  const [outputs, setOutputs] = useState<OutputsResponse | null>(null);

  useEffect(() => {
    void api.transcript(meetingId).then(setTranscript);
  }, [meetingId]);

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

  const decisions = outputs?.decisions ?? [];
  const actions = outputs?.action_items ?? [];

  const speaker = (participantId: string) =>
    transcript?.participants.find((p) => p.id === participantId)?.display_name ?? "Participant";

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
                    <span className="evidence">{d.evidence_segment_ids.length} extrait(s)</span>
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
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      <h3 className="transcript-heading">Transcript</h3>
      <div className="transcript">
        {transcript?.segments.map((segment) => (
          <p key={segment.id} className="line line-final">
            <span className="speaker">{speaker(segment.participant_id)}</span>
            {segment.text}
          </p>
        ))}
      </div>
    </>
  );
}
