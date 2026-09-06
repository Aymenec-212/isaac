import { useState } from "react";
import { token } from "./api/client";
import { Mark } from "./meeting/Mark";
import { MeetingList } from "./meeting/MeetingList";
import { TokenGate } from "./meeting/TokenGate";

export default function App() {
  const [authenticated, setAuthenticated] = useState(() => token.get() !== null);

  return (
    <div className="shell">
      <aside className="rail">
        <div className="wordmark">
          <Mark />
          <h1>Mosaïque</h1>
        </div>
        <p>Transcription et mémoire de réunion, en français.</p>
        <div className="rail-foot">
          Prototype · Tranche 0
          {authenticated && (
            <>
              <br />
              <button
                className="btn-quiet"
                style={{ marginTop: 10, padding: "5px 10px", fontSize: 12 }}
                onClick={() => {
                  token.clear();
                  setAuthenticated(false);
                }}
              >
                Changer de jeton
              </button>
            </>
          )}
        </div>
      </aside>
      <main className="main">
        {authenticated ? <MeetingList /> : <TokenGate onReady={() => setAuthenticated(true)} />}
      </main>
    </div>
  );
}
