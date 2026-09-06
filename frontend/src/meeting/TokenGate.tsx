import { useState } from "react";
import { token } from "../api/client";

/**
 * Slice 0 stands in for login (blueprint R-2): paste the host token printed by
 * `seed.py`. Magic-link authentication replaces this in Slice 7; nothing else
 * in the app knows the difference, because everything reads `token`.
 */
export function TokenGate({ onReady }: { onReady: () => void }) {
  const [value, setValue] = useState("");
  return (
    <>
      <div className="head">
        <div>
          <h2>Connexion au pilote</h2>
          <p>Collez le jeton affiché par le script d'amorçage pour continuer.</p>
        </div>
      </div>
      <div className="field-row">
        <input
          type="text"
          value={value}
          placeholder="Jeton hôte"
          aria-label="Jeton hôte"
          onChange={(e) => setValue(e.target.value)}
        />
        <button
          className="btn-primary"
          disabled={!value.trim()}
          onClick={() => {
            token.set(value.trim());
            onReady();
          }}
        >
          Continuer
        </button>
      </div>
      <div className="empty">
        <strong>Où trouver ce jeton</strong>
        Lancez <code>uv run python -m mosaique.app.seed</code> dans le dossier backend.
      </div>
    </>
  );
}
