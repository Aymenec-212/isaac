import { useState } from "react";
import { ApiError, api, type JoinResponse } from "../api/client";

/**
 * Consent comes before the microphone prompt, never after (tech spec 13.3).
 * Headphone guidance is here because in this prototype every participant's
 * microphone can pick up the others through a loudspeaker, which misattributes
 * speech to whoever is on speakers.
 */
export function JoinPage({
  meetingId,
  inviteToken,
  onJoined,
}: {
  meetingId: string;
  inviteToken: string;
  onJoined: (joined: JoinResponse) => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [joining, setJoining] = useState(false);

  async function join() {
    if (!displayName.trim()) return;
    setJoining(true);
    try {
      onJoined(await api.join(meetingId, displayName.trim(), inviteToken));
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setJoining(false);
    }
  }

  return (
    <>
      <div className="head">
        <div>
          <h2>Rejoindre la réunion</h2>
          <p>Votre micro sera transcrit en direct.</p>
        </div>
      </div>

      <div className="consent">
        <strong>Cette réunion est enregistrée et transcrite.</strong>
        <p>
          Votre audio est enregistré pour produire le transcript et le compte rendu.
          En rejoignant, vous y consentez. Prévenez les autres participants.
        </p>
        <p className="consent-tip">
          Utilisez un casque : sans casque, votre micro capte aussi la voix des
          autres et le transcript leur attribue mal la parole.
        </p>
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
          value={displayName}
          placeholder="Votre nom"
          aria-label="Votre nom"
          onChange={(e) => setDisplayName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void join()}
        />
        <button className="btn-primary" disabled={joining || !displayName.trim()} onClick={() => void join()}>
          {joining ? "Connexion…" : "Rejoindre et autoriser le micro"}
        </button>
      </div>
    </>
  );
}
