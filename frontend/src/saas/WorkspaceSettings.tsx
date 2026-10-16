import { useEffect, useState, type FormEvent } from "react";
import { request, type Workspace } from "./client";
import type { components } from "./schema";

export default function WorkspaceSettings({
  workspace,
  csrf,
  onRename,
  onError,
}: {
  workspace: Workspace;
  csrf: string;
  onRename: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const org = workspace.id;
  const [rename, setRename] = useState(workspace.name);
  const [email, setEmail] = useState("");
  const [invitation, setInvitation] = useState("");
  const [pending, setPending] = useState<
    components["schemas"]["InvitationView"][]
  >([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setRename(workspace.name);
  }, [workspace.name]);
  useEffect(() => {
    let active = true;
    void request<components["schemas"]["InvitationView"][]>(
      `/workspaces/${org}/invitations`,
    )
      .then((list) => {
        if (active) setPending(list);
      })
      .catch((error) => {
        if (active) onError(error);
      });
    return () => {
      active = false;
    };
  }, [org, invitation, onError]);
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
      <h2>Paramètres de l’espace</h2>
      <form
        onSubmit={submit(async () => {
          await request(`/workspaces/${org}`, csrf, "PATCH", {
            name: rename,
          });
          await onRename();
        })}
      >
        <label>
          Nom de l’espace
          <input
            required
            maxLength={200}
            value={rename}
            onChange={(e) => setRename(e.target.value)}
          />
        </label>
        <button disabled={busy}>Renommer</button>
      </form>
      <h3>Inviter un collègue</h3>
      <form
        onSubmit={submit(async () => {
          const invite = await request<{ token: string }>(
            `/workspaces/${org}/invitations`,
            csrf,
            "POST",
            { email },
          );
          setInvitation(
            `${window.location.origin}/#invitation=${encodeURIComponent(invite.token)}`,
          );
          setEmail("");
        })}
      >
        <label>
          Adresse e-mail
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <button disabled={busy}>Créer une invitation</button>
      </form>
      {invitation && (
        <label>
          Lien à partager · valable 7 jours
          <input
            aria-label="Lien d’invitation"
            readOnly
            value={invitation}
            onFocus={(e) => e.target.select()}
          />
        </label>
      )}
      {pending.length > 0 && (
        <>
          <h3>Invitations en attente</h3>
          <ul className="saas-list">
            {pending.map((i) => (
              <li key={i.id}>
                <span>
                  {i.email}
                  <small>
                    Expire le {new Date(i.expires_at).toLocaleDateString("fr")}
                  </small>
                </span>
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      await request(
                        `/workspaces/${org}/invitations/${i.id}`,
                        csrf,
                        "DELETE",
                      );
                      setPending(pending.filter((p) => p.id !== i.id));
                    })
                  }
                >
                  Révoquer l’invitation
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
