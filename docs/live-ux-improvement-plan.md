# Mosaïque live UX improvement plan

Implementation status: complete. The frontend changes below are implemented on
`codex/frontend-glass-polish`; the automated checks pass, and the live browser
run verified the dashboard, join, live, mute, finalization, and review flows.

## Scope

This plan captures findings from a real local run of the dashboard, join flow,
live meeting, mute state, finalization, and review handoff. The work stays in
the frontend. API calls, authentication, routing, meeting lifecycle, WebRTC,
microphone capture, and backend behavior remain unchanged.

## Findings and acceptance criteria

1. **Complete —** Mobile meeting actions consume too much vertical space.
   - Use a compact, responsive action group while keeping the existing labels,
     keyboard access, and disabled states.
   - Acceptance: the three actions remain reachable on mobile without three
     full-width rows dominating the first viewport.

2. **Complete —** A one-person participant panel has excessive empty space.
   - Make the roster content-sized with a sensible maximum width and preserve
     wrapping for larger groups.
   - Acceptance: one participant reads as a compact floating strip; multiple
     participants still wrap cleanly.

3. **Complete —** Live status labels are ambiguous.
   - Distinguish transcription, microphone, and direct voice states in visible
     copy and accessible text.
   - Acceptance: a participant can tell which subsystem is waiting or failing.

4. **Complete —** The no-audio state does not change the waveform enough.
   - Dim the waveform and add a clear muted/no-audio visual state without
     changing capture logic.
   - Acceptance: muted and silent states are visibly different from active
     microphone input.

5. **Complete —** Finalization provides little progress feedback.
   - Add a live status notice while controls are disabled and finalization is in
     progress.
   - Acceptance: the participant understands that the meeting is being sealed
     and that the review page will follow.

6. **Complete —** Review navigation preserves the live page's scroll position.
   - Reset scroll to the top when the routed view changes.
   - Acceptance: the review heading and back action are visible immediately
     after finalization.

7. **Complete —** The dashboard becomes difficult to manage with many meetings.
   - Add client-side search and state filtering without changing the list API.
   - Acceptance: users can quickly narrow the existing meeting list and clear
     filters when there are no matches.

8. **Complete —** The native live audio player is confusing when no remote stream exists.
   - Keep the audio element available for WebRTC playback, but visually hide
     the empty browser player; show the recovery action only when autoplay is
     blocked.
   - Acceptance: no empty `0:00 / 0:00` player appears, and remote playback
     remains available to the existing WebRTC flow.

## Verification

- Frontend unit tests and contrast check.
- Typecheck and production build.
- Targeted browser checks for dashboard filtering, live action states,
  no-audio/muted styling, finalization notice, review scroll reset, and hidden
  native audio controls.

The browser session verified dashboard search/filter behavior and review scroll
reset after implementation. The earlier live run verified join, mute/unmute,
waveform visibility, finalization, and review handoff; the final browser session
ended before the last no-audio/finalization recheck could be repeated.
