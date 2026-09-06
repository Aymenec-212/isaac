import { useCallback, useEffect, useState } from "react";
import { ApiError, api, token, type Meeting } from "../api/client";

const STATE_LABELS: Record<string, string> = {
  CREATED: "Créée",
  JOINABLE: "Ouverte",
  LIVE: "En cours",
  FINALIZING: "Finalisation",
  COMPLETED: "Terminée",
  FAILED: "Échec",
  CANCELLED: "Annulée",
};

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function MeetingList() {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const { meetings } = await api.listMeetings();
      setMeetings(meetings);
      setError(null);
    } catch (e) {
      setError(e as ApiError);
      setMeetings([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function create() {
    if (!title.trim()) return;
    setCreating(true);
    try {
      const created = await api.createMeeting(title.trim());
      token.set(created.host_token);
      setTitle("");
      await load();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <div className="head">
        <div>
          <h2>Vos réunions</h2>
          <p>Chaque réunion conserve son transcript et ses décisions.</p>
        </div>
      </div>

      {error && (
        <div className="notice" role="alert">
          <div>{error.message}</div>
          {error.requestId && <code>Référence : {error.requestId}</code>}
        </div>
      )}

      <div className="field-row">
        <input
          type="text"
          value={title}
          placeholder="Titre de la réunion"
          aria-label="Titre de la réunion"
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void create()}
        />
        <button className="btn-primary" onClick={() => void create()} disabled={creating || !title.trim()}>
          {creating ? "Création…" : "Nouvelle réunion"}
        </button>
      </div>

      {meetings === null ? (
        <div className="empty">Chargement…</div>
      ) : meetings.length === 0 ? (
        <div className="empty">
          <strong>Aucune réunion pour l'instant</strong>
          Donnez un titre ci-dessus pour créer la première.
        </div>
      ) : (
        <div className="ledger">
          {meetings.map((m) => (
            <div className="row" key={m.id}>
              <p className="row-title">{m.title}</p>
              <span className="state">
                <span className="tessera" data-state={m.state} />
                {STATE_LABELS[m.state] ?? m.state}
              </span>
              <span className="row-meta">{formatDate(m.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
