import { useState, type FormEvent } from "react";
import { request, type Account, type Member, type Meeting } from "./client";

export default function MeetingsPanel({
  org,
  account,
  members,
  meetings,
  onChanged,
  onError,
}: {
  org: string;
  account: Account;
  members: Member[];
  meetings: Meeting[];
  onChanged: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [title, setTitle] = useState("");
  const [grants, setGrants] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const csrf = account.csrf_token;
  async function act(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try {
      await action();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  const submit = (action: () => Promise<void>) => (event: FormEvent) => {
    event.preventDefault();
    void act(action);
  };
  return (
    <section className="saas-card">
      <h2>Réunions privées</h2>
      <p>
        Seuls l’organisateur et les membres autorisés peuvent voir une réunion.
        Les appels audio seront disponibles à une prochaine étape.
      </p>
      <form
        onSubmit={submit(async () => {
          await request(`/workspaces/${org}/meetings`, csrf, "POST", {
            title,
          });
          setTitle("");
          await onChanged();
        })}
      >
        <label>
          Titre de la réunion
          <input
            required
            maxLength={200}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <button disabled={busy}>Préparer une réunion</button>
      </form>
      {meetings.length === 0 ? (
        <p>Aucune réunion accessible dans cet espace.</p>
      ) : (
        <ul className="saas-list">
          {meetings.map((m) => (
            <li key={m.id}>
              <div>
                <strong>{m.title}</strong>
                <small>
                  Préparée le {new Date(m.created_at).toLocaleDateString("fr")}{" "}
                  · {m.state === "CREATED" ? "Préparée" : "État indisponible"}
                </small>
                {m.organizer_account_id === account.id && (
                  <details
                    onToggle={(e) => {
                      if (e.currentTarget.open)
                        void request<string[]>(
                          `/workspaces/${org}/meetings/${m.id}/access`,
                        )
                          .then((ids) =>
                            setGrants((prev) => ({
                              ...prev,
                              [m.id]: ids,
                            })),
                          )
                          .catch(onError);
                    }}
                  >
                    <summary>Gérer l’accès</summary>
                    {members
                      .filter((person) => person.id !== account.id)
                      .map((person) => (
                        <div className="saas-actions" key={person.id}>
                          <span>
                            {person.display_name || person.email} ·{" "}
                            {grants[m.id]?.includes(person.id)
                              ? "Autorisé"
                              : "Accès privé"}
                          </span>
                          <button
                            disabled={busy}
                            onClick={() =>
                              void act(async () => {
                                await request(
                                  `/workspaces/${org}/meetings/${m.id}/access/${person.id}`,
                                  csrf,
                                  "PUT",
                                  { allow: true },
                                );
                                setGrants((prev) => ({
                                  ...prev,
                                  [m.id]: [...(prev[m.id] ?? []), person.id],
                                }));
                              })
                            }
                          >
                            Autoriser
                          </button>
                          <button
                            disabled={busy}
                            onClick={() =>
                              void act(async () => {
                                await request(
                                  `/workspaces/${org}/meetings/${m.id}/access/${person.id}`,
                                  csrf,
                                  "PUT",
                                  { allow: false },
                                );
                                setGrants((prev) => ({
                                  ...prev,
                                  [m.id]: (prev[m.id] ?? []).filter(
                                    (id) => id !== person.id,
                                  ),
                                }));
                              })
                            }
                          >
                            Retirer l’accès
                          </button>
                        </div>
                      ))}
                  </details>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
