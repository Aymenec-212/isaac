import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Mark } from "../meeting/Mark";
import {
  request,
  SessionError,
  type Account,
  type Workspace,
  type Member,
  type Meeting,
} from "./client";
import "./saas.css";
import { roleLabel, auditLabel } from "./labels";
import MeetingsPanel from "./MeetingsPanel";
import WorkspaceSettings from "./WorkspaceSettings";

export default function SaasApp() {
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [configured, setConfigured] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [org, setOrg] = useState("");
  const [members, setMembers] = useState<Member[]>([]);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [audit, setAudit] = useState<
    { id: string; action: string; actor_id: string; created_at: string }[]
  >([]);
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [acceptToken, setAcceptToken] = useState(
    () =>
      new URLSearchParams(window.location.hash.slice(1)).get("invitation") ??
      sessionStorage.getItem("mosaique.invitation") ??
      "",
  );
  const generation = useRef(0);
  const selected = workspaces.find((w) => w.id === org);

  useEffect(() => {
    // Invitation secrets stay out of HTTP access logs and referrers.
    const incoming = new URLSearchParams(window.location.hash.slice(1)).get(
      "invitation",
    );
    if (incoming) sessionStorage.setItem("mosaique.invitation", incoming);
    if (window.location.hash)
      window.history.replaceState({}, "", window.location.pathname);
    let active = true;
    void fetch("/api/auth/status")
      .then((r) => r.json())
      .then((s: { configured: boolean }) => {
        if (active) setConfigured(s.configured);
      })
      .catch(() => undefined);
    void request<Account>("/me")
      .then(async (a) => {
        const list = await request<Workspace[]>("/workspaces");
        if (!active) return;
        setAccount(a);
        setDisplayName(a.display_name);
        setWorkspaces(list);
        const remembered = localStorage.getItem(`mosaique.workspace.${a.id}`);
        setOrg(list.find((w) => w.id === remembered)?.id ?? list[0]?.id ?? "");
      })
      .catch((e) => {
        if (active && (!(e instanceof SessionError) || e.status !== 401))
          setError(String(e.message));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (account && org && workspaces.some((w) => w.id === org))
      localStorage.setItem(`mosaique.workspace.${account.id}`, org);
  }, [account, org, workspaces]);

  const refresh = useCallback(async (id: string) => {
    const current = ++generation.current;
    setMembers([]);
    setMeetings([]);
    setAudit([]);
    const [people, meetings] = await Promise.all([
      request<Member[]>(`/workspaces/${id}/members`),
      request<Meeting[]>(`/workspaces/${id}/meetings`),
    ]);
    if (current === generation.current) {
      setMembers(people);
      setMeetings(meetings);
    }
  }, []);

  useEffect(() => {
    if (!account) return;
    let last = Date.now();
    const activity = () => {
      if (
        document.visibilityState !== "visible" ||
        Date.now() - last < 5 * 60_000
      )
        return;
      last = Date.now();
      void request("/session/activity", account.csrf_token, "POST").catch(
        (e) => {
          if (e instanceof SessionError && e.status === 401) {
            setAccount(null);
            setError(
              "Votre session a expiré. Reconnectez-vous pour continuer.",
            );
          }
        },
      );
    };
    window.addEventListener("pointerdown", activity);
    window.addEventListener("keydown", activity);
    return () => {
      window.removeEventListener("pointerdown", activity);
      window.removeEventListener("keydown", activity);
    };
  }, [account]);

  const invalidate = useCallback(() => {
    generation.current++;
  }, []);

  useEffect(() => {
    if (!org) {
      setMembers([]);
      setMeetings([]);
      return;
    }
    void refresh(org).catch((e) => setError(e.message));
    return invalidate;
  }, [org, selected?.name, refresh, invalidate]);

  const handleError = useCallback((error: unknown) => {
    setError(error instanceof Error ? error.message : "Demande indisponible");
    if (error instanceof SessionError && error.status === 401) setAccount(null);
  }, []);

  async function act(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      handleError(e);
    } finally {
      setBusy(false);
    }
  }
  const submit = (action: () => Promise<void>) => (event: FormEvent) => {
    event.preventDefault();
    void act(action);
  };
  const csrf = account?.csrf_token;
  const manage = selected?.role === "owner" || selected?.role === "admin";

  return (
    <div className="saas-shell">
      <header className="saas-header">
        <a href="/" className="saas-brand">
          <Mark /> Mosaïque
        </a>
        {account && (
          <button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                await request("/logout", csrf, "POST");
                generation.current++;
                setAccount(null);
                setWorkspaces([]);
                setMembers([]);
                setMeetings([]);
              })
            }
          >
            Se déconnecter
          </button>
        )}
      </header>
      <main className="saas-main">
        {error && (
          <div role="alert" className="saas-error">
            {error}
          </div>
        )}
        {loading ? (
          <p role="status">Chargement de votre compte…</p>
        ) : !account ? (
          <section className="saas-card">
            <p className="eyebrow">Votre espace de travail</p>
            <h1>La mémoire de vos réunions commence ici.</h1>
            <p>
              Connectez-vous pour gérer vos espaces et préparer vos réunions
              privées.
            </p>
            {configured ? (
              <a className="saas-primary" href="/api/auth/login">
                Se connecter ou créer un compte
              </a>
            ) : (
              <p role="status">
                La connexion sécurisée doit être configurée par votre
                administrateur.
              </p>
            )}
            <p>
              La récupération de compte est disponible sur la page de connexion
              sécurisée.
            </p>
          </section>
        ) : (
          <>
            <div className="saas-heading">
              <div>
                <p className="eyebrow">Espace de travail</p>
                <h1>{selected?.name ?? "Bienvenue dans Mosaïque"}</h1>
              </div>
              <label>
                Changer d’espace
                <select
                  aria-label="Changer d’espace"
                  disabled={busy}
                  value={org}
                  onChange={(e) => {
                    setError("");
                    setOrg(e.target.value);
                  }}
                >
                  <option value="" disabled>
                    Choisissez un espace
                  </option>
                  {workspaces.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="saas-grid">
              <section className="saas-card">
                <h2>Votre profil</h2>
                <p>
                  {account.email} ·{" "}
                  {account.email_verified
                    ? "Adresse vérifiée"
                    : "Adresse à vérifier pour accepter une invitation"}
                </p>
                <form
                  onSubmit={submit(async () => {
                    await request("/me", csrf, "PATCH", {
                      display_name: displayName,
                    });
                    setAccount({
                      ...account,
                      display_name: displayName.trim(),
                    });
                  })}
                >
                  <label>
                    Nom affiché
                    <input
                      required
                      maxLength={120}
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                    />
                  </label>
                  <button disabled={busy}>Enregistrer le profil</button>
                </form>
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      await request("/logout-all", csrf, "POST");
                      generation.current++;
                      setAccount(null);
                      setWorkspaces([]);
                      setMembers([]);
                      setMeetings([]);
                    })
                  }
                >
                  Déconnecter toutes mes sessions
                </button>
              </section>
              <section className="saas-card">
                <h2>Créer un espace</h2>
                <form
                  onSubmit={submit(async () => {
                    const w = await request<Workspace>(
                      "/workspaces",
                      csrf,
                      "POST",
                      { name },
                    );
                    setName("");
                    setWorkspaces(await request("/workspaces"));
                    setOrg(w.id);
                  })}
                >
                  <label>
                    Nom de l’espace
                    <input
                      required
                      maxLength={200}
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </label>
                  <button disabled={busy}>Créer l’espace</button>
                </form>
              </section>
              <section className="saas-card">
                <h2>Accepter une invitation</h2>
                <p>Utilisez le compte correspondant à l’adresse invitée.</p>
                <form
                  onSubmit={submit(async () => {
                    const w = await request<Workspace>(
                      "/invitations/accept",
                      csrf,
                      "POST",
                      { token: acceptToken },
                    );
                    setAcceptToken("");
                    sessionStorage.removeItem("mosaique.invitation");
                    setWorkspaces(await request("/workspaces"));
                    setOrg(w.id);
                    await refresh(w.id);
                  })}
                >
                  <label>
                    Code d’invitation
                    <input
                      required
                      maxLength={128}
                      autoComplete="off"
                      value={acceptToken}
                      onChange={(e) => setAcceptToken(e.target.value)}
                    />
                  </label>
                  <button disabled={busy}>Rejoindre l’espace</button>
                </form>
              </section>
              {selected && manage && (
                <WorkspaceSettings
                  key={org}
                  workspace={selected}
                  csrf={account.csrf_token}
                  onRename={async () =>
                    setWorkspaces(await request("/workspaces"))
                  }
                  onError={handleError}
                />
              )}
            </div>
            {selected && (
              <section className="saas-card">
                <h2>Membres</h2>
                <ul className="saas-list">
                  {members.map((m) => (
                    <li key={m.id}>
                      <span>
                        {m.display_name || m.email}
                        <small>{m.email}</small>
                      </span>
                      {selected.role === "owner" ? (
                        <div className="saas-actions">
                          <select
                            aria-label={`Rôle de ${m.email}`}
                            value={m.role}
                            disabled={busy}
                            onChange={(e) =>
                              void act(async () => {
                                await request(
                                  `/workspaces/${org}/members/${m.id}`,
                                  csrf,
                                  "PATCH",
                                  { role: e.target.value },
                                );
                                setWorkspaces(await request("/workspaces"));
                                await refresh(org);
                              })
                            }
                          >
                            {["member", "admin", "owner"].map((role) => (
                              <option key={role} value={role}>{roleLabel[role]}</option>
                            ))}
                          </select>
                          <button
                            disabled={busy}
                            onClick={() =>
                              void act(async () => {
                                await request(
                                  `/workspaces/${org}/members/${m.id}`,
                                  csrf,
                                  "PATCH",
                                  { role: null },
                                );
                                const list =
                                  await request<Workspace[]>("/workspaces");
                                setWorkspaces(list);
                                if (m.id === account.id)
                                  setOrg(list[0]?.id ?? "");
                                else await refresh(org);
                              })
                            }
                          >
                            Retirer
                          </button>
                        </div>
                      ) : (
                        <span>{roleLabel[m.role]}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {selected && (
              <MeetingsPanel
                key={org}
                org={org}
                account={account}
                members={members}
                meetings={meetings}
                onChanged={() => refresh(org)}
                onError={handleError}
              />
            )}
            {selected && manage && (
              <section className="saas-card">
                <h2>Journal de l’espace</h2>
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      setAudit(await request(`/workspaces/${org}/audit`));
                    })
                  }
                >
                  Afficher les dernières opérations
                </button>
                <ul className="saas-list">
                  {audit.map((e) => (
                    <li key={e.id}>
                      <span>
                        {auditLabel(e.action)}
                        <small>
                          {new Date(e.created_at).toLocaleString("fr")} ·{" "}
                          {members.find((m) => m.id === e.actor_id)
                            ?.display_name || e.actor_id}
                        </small>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
