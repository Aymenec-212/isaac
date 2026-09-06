import { useCallback, useEffect, useState } from "react";
import { type JoinResponse, token } from "./api/client";
import { Mark } from "./meeting/Mark";
import { JoinPage } from "./meeting/JoinPage";
import { LiveMeeting } from "./meeting/LiveMeeting";
import { MeetingList } from "./meeting/MeetingList";
import { TokenGate } from "./meeting/TokenGate";
import { ReviewPage } from "./review/ReviewPage";

type View =
  | { name: "list" }
  | { name: "join"; meetingId: string; inviteToken: string }
  | { name: "live"; joined: JoinResponse }
  | { name: "review"; meetingId: string };

/** Reads `/join/{id}?t={token}` so an invite link opens straight into consent. */
function viewFromLocation(): View {
  const path = window.location.pathname;
  const joinMatch = path.match(/^\/join\/([A-Z0-9]{26})$/i);
  if (joinMatch?.[1]) {
    const inviteToken = new URLSearchParams(window.location.search).get("t");
    if (inviteToken) return { name: "join", meetingId: joinMatch[1], inviteToken };
  }
  const reviewMatch = path.match(/^\/review\/([A-Z0-9]{26})$/i);
  if (reviewMatch?.[1]) return { name: "review", meetingId: reviewMatch[1] };
  return { name: "list" };
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(() => token.get() !== null);
  const [view, setView] = useState<View>(viewFromLocation);

  useEffect(() => {
    const onPop = () => setView(viewFromLocation());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const goToList = useCallback(() => {
    window.history.pushState({}, "", "/");
    setView({ name: "list" });
  }, []);

  const isJoinFlow = view.name === "join" || view.name === "live";
  const openReview = useCallback((meetingId: string) => {
    window.history.pushState({}, "", `/review/${meetingId}`);
    setView({ name: "review", meetingId });
  }, []);

  return (
    <div className="shell">
      <aside className="rail">
        <div className="wordmark">
          <Mark />
          <h1>Mosaïque</h1>
        </div>
        <p>Transcription et mémoire de réunion, en français.</p>
        <div className="rail-foot">
          Prototype · Tranche 1
          {authenticated && !isJoinFlow && (
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
        {view.name === "join" ? (
          <JoinPage
            meetingId={view.meetingId}
            inviteToken={view.inviteToken}
            onJoined={(joined) => setView({ name: "live", joined })}
          />
        ) : view.name === "live" ? (
          <LiveMeeting
            joined={view.joined}
            isHost={authenticated}
            onEnded={() => openReview(view.joined.meeting.id)}
          />
        ) : !authenticated ? (
          <TokenGate onReady={() => setAuthenticated(true)} />
        ) : view.name === "review" ? (
          <ReviewPage meetingId={view.meetingId} onBack={goToList} />
        ) : (
          <MeetingList onOpenReview={openReview} />
        )}
      </main>
    </div>
  );
}
