import { useCallback, useEffect, useState } from "react";
import { type JoinResponse, token, api, meetingCredentials } from "./api/client";
import { HealthBanner } from "./health/HealthBanner";
import { ReadinessProvider } from "./health/ReadinessProvider";
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
  | { name: "review"; meetingId: string }
  | { name: "restore"; meetingId: string; inviteToken?: string }
  | { name: "notice"; message: string };

/** Reads `/join/{id}?t={token}` so an invite link opens straight into consent. */
function viewFromLocation(): View {
  const path = window.location.pathname;
  const joinMatch = path.match(/^\/join\/([A-Z0-9]{26})$/i);
  if (joinMatch?.[1]) {
    const inviteToken = new URLSearchParams(window.location.search).get("t");
    if (inviteToken) {
      if (meetingCredentials.get(joinMatch[1])) return { name: "restore", meetingId: joinMatch[1], inviteToken };
      return { name: "join", meetingId: joinMatch[1], inviteToken };
    }
  }
  const liveMatch = path.match(/^\/meeting\/([A-Z0-9]{26})$/i);
  if (liveMatch?.[1]) return { name: "restore", meetingId: liveMatch[1] };
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

  useEffect(() => {
    if (view.name !== "restore") return;
    let cancelled = false;
    const joined = meetingCredentials.get(view.meetingId);
    if (!joined) {
      setView({ name: "notice", message: "Ouvrez votre lien d'invitation pour rejoindre cette réunion." });
      return;
    }
    void api.getMeeting(view.meetingId).then((meeting) => {
      if (cancelled) return;
      if (["COMPLETED", "FAILED", "FINALIZING"].includes(meeting.state)) {
        window.history.replaceState({}, "", `/review/${meeting.id}`);
        setView({ name: "review", meetingId: meeting.id });
      } else {
        setView({ name: "live", joined: { ...joined, meeting, can_manage: meeting.can_manage } });
      }
    }).catch(() => {
      if (cancelled) return;
      if (view.inviteToken) setView({ name: "join", meetingId: view.meetingId, inviteToken: view.inviteToken });
      else setView({ name: "notice", message: "Accès indisponible. Réessayez avec votre lien d'invitation." });
    });
    return () => { cancelled = true; };
  }, [view]);

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
    <ReadinessProvider>
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
          {/* Above the view, not inside it: a dependency being down is true on
              every screen, and the join page is exactly where someone most needs
              to be told before they start talking. */}
          <HealthBanner />

          {view.name === "notice" ? <div className="notice" role="alert">{view.message}</div> :
           view.name === "restore" ? <div className="empty">Reconnexion à la réunion…</div> :
           view.name === "join" ? (
            <JoinPage
              meetingId={view.meetingId}
              inviteToken={view.inviteToken}
              onJoined={(joined) => {
                window.history.pushState({}, "", `/meeting/${joined.meeting.id}`);
                setView({ name: "live", joined });
              }}
            />
          ) : view.name === "live" ? (
            <LiveMeeting
              joined={view.joined}
              isHost={view.joined.can_manage}
              onEnded={() => openReview(view.joined.meeting.id)}
            />
          ) : !authenticated && !(view.name === "review" && meetingCredentials.get(view.meetingId)) ? (
            <TokenGate onReady={() => setAuthenticated(true)} />
          ) : view.name === "review" ? (
            <ReviewPage meetingId={view.meetingId} onBack={goToList} />
          ) : (
            <MeetingList onOpenReview={openReview} />
          )}
        </main>
      </div>
    </ReadinessProvider>
  );
}
