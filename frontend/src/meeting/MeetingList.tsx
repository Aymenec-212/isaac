import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api, token, type Meeting } from "../api/client";
import { useReadiness } from "../health/ReadinessProvider";
import { creationBlockedReason, meetingCreationBlocked } from "../health/status";

const STATE_LABELS: Record<string, string> = {
  CREATED: "Créée",
  JOINABLE: "Ouverte",
  LIVE: "En cours",
  FINALIZING: "Finalisation",
  COMPLETED: "Terminée",
  FAILED: "Échec",
  CANCELLED: "Annulée",
};

const STATE_FILTERS = [
  "ALL",
  "JOINABLE",
  "LIVE",
  "FINALIZING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
] as const;

type StateFilter = (typeof STATE_FILTERS)[number];

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function MeetingList({ onOpenReview }: { onOpenReview: (meetingId: string) => void }) {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [creating, setCreating] = useState(false);
  const [invite, setInvite] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState<StateFilter>("ALL");

  // The same readiness the banner above is rendering, from the same poll. A
  // meeting whose transcription engine is down records audio nobody can read,
  // so the honest thing is to refuse it here rather than to warn and allow.
  const readiness = useReadiness();
  const blocked = meetingCreationBlocked(readiness);

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
    if (!title.trim() || blocked) return;
    setCreating(true);
    try {
      const created = await api.createMeeting(title.trim());
      token.set(created.host_token);
      setInvite(created.invite_url);
      setTitle("");
      await load();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setCreating(false);
    }
  }

  const visibleMeetings = useMemo(() => {
    if (!meetings) return [];
    const wanted = query.trim().toLocaleLowerCase("fr-FR");
    return meetings.filter((meeting) => {
      const matchesQuery = !wanted || meeting.title.toLocaleLowerCase("fr-FR").includes(wanted);
      const matchesState = stateFilter === "ALL" || meeting.state === stateFilter;
      return matchesQuery && matchesState;
    });
  }, [meetings, query, stateFilter]);

  const filtersActive = query.trim().length > 0 || stateFilter !== "ALL";
  const clearFilters = () => {
    setQuery("");
    setStateFilter("ALL");
  };

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
        <button
          className="btn-primary"
          onClick={() => void create()}
          disabled={creating || !title.trim() || blocked}
          aria-describedby={blocked ? "creation-blocked" : undefined}
        >
          {creating ? "Création…" : "Nouvelle réunion"}
        </button>
      </div>

      {/* A disabled control with no stated reason is worse than one that fails
          loudly. The banner above carries the full consequence; this is the one
          line needed at the moment someone clicks and nothing happens. */}
      {blocked && (
        <p className="field-note" id="creation-blocked" role="status">
          {creationBlockedReason(readiness)}
        </p>
      )}

      {invite && (
        <div className="notice">
          <div>Lien d'invitation créé. Ouvrez-le pour rejoindre et parler.</div>
          <a href={invite}>{invite}</a>
        </div>
      )}

      {meetings && meetings.length > 0 && (
        <div className="meeting-filters" role="search" aria-label="Rechercher dans vos réunions">
          <input
            type="search"
            value={query}
            placeholder="Rechercher une réunion…"
            aria-label="Rechercher une réunion"
            onChange={(event) => setQuery(event.target.value)}
          />
          <select
            value={stateFilter}
            aria-label="Filtrer les réunions par état"
            onChange={(event) => setStateFilter(event.target.value as StateFilter)}
          >
            <option value="ALL">Tous les états</option>
            {STATE_FILTERS.filter((state) => state !== "ALL").map((state) => (
              <option key={state} value={state}>
                {STATE_LABELS[state]}
              </option>
            ))}
          </select>
          {filtersActive && (
            <button type="button" className="btn-quiet" onClick={clearFilters}>
              Effacer
            </button>
          )}
        </div>
      )}

      {meetings === null ? (
        <div className="empty">Chargement…</div>
      ) : meetings.length === 0 ? (
        <div className="empty">
          <strong>Aucune réunion pour l'instant</strong>
          Donnez un titre ci-dessus pour créer la première.
        </div>
      ) : visibleMeetings.length === 0 ? (
        <div className="empty">
          <strong>Aucune réunion trouvée</strong>
          Modifiez votre recherche ou votre filtre pour afficher d'autres réunions.
          <button type="button" className="btn-quiet empty-action" onClick={clearFilters}>
            Effacer les filtres
          </button>
        </div>
      ) : (
        <div className="ledger">
          {visibleMeetings.map((m) => (
            <div
              className="row row-clickable"
              key={m.id}
              role="button"
              tabIndex={0}
              onClick={() => m.state === "COMPLETED" && onOpenReview(m.id)}
              onKeyDown={(e) => e.key === "Enter" && m.state === "COMPLETED" && onOpenReview(m.id)}
            >
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
