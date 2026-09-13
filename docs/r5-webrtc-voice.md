# R5 — direct WebRTC voice

R4 is the baseline (`1e48a9a`, merged PR #23). This slice adds the browser
voice plane without changing the PCM WebSocket transcription path or the
`StreamingRecognizer` seam. Browser audio is sent directly between the two
participants when possible and through the configured TURN service otherwise.
The app-server carries only signaling and never receives conversational media.

## Contracts

`GET /meetings/{meeting_id}/ice-config` requires the existing host or
meeting-scoped participant credential. It returns configured STUN URLs and,
when TURN is configured, a coturn REST credential:

```json
{
  "ice_servers": [{"urls": ["turn:turn.example:3478"], "username": "<expiry>:<random>", "credential": "<hmac-sha1>"}],
  "expires_at": "<UTC timestamp>"
}
```

The browser never receives `MOSAIQUE_WEBRTC_TURN_SHARED_SECRET`. The secret is
used only by the app-server to derive the expiring username and credential.
Missing TURN configuration is an explicit direct-connect-only mode, not a
claim that cross-network calls work.

The authenticated meeting WebSocket accepts version-one `rtc.offer`,
`rtc.answer`, and `rtc.ice` messages with a target participant. The gateway
derives the sender from the socket, checks that the target is currently
connected in the same meeting, and forwards a message with
`from_participant_id`. A sender cannot target itself; stale/replaced sockets
are rejected by the existing R4 ownership check.

`audio.flush` carries the sender's last sequence and receives
`audio.flush.ok`. When the host calls end, the server sends
`meeting.end_requested`, waits up to two seconds for every currently connected
participant to acknowledge the flush, then enters the existing runtime drain.
The deadline is shared; a missing peer is logged as incomplete and does not
hold finalization open indefinitely.

## Browser behavior

`MicrophoneCapture` exposes the one acquired `MediaStream` to both consumers:
the existing 24 kHz PCM worklet and `WebRTCVoice`. A deterministic participant
ordering chooses the offerer, preventing simultaneous negotiation glare. ICE
candidates are queued until the peer description exists. Mute disables the
track and suppresses PCM frames together; remote playback remains active.

Leave closes the peer connection and the transcription socket for that
participant. Host end flushes local input before the existing HTTP end route.
Remote autoplay failure leaves an explicit play control. Voice state is shown
separately from ASR state, so a working call does not imply transcription or
recording health.

## Configuration

Set these optional app-server settings for a real deployment:

```text
MOSAIQUE_WEBRTC_STUN_URLS=["stun:stun.example:3478"]
MOSAIQUE_WEBRTC_TURN_URLS=["turn:turn.example:3478?transport=udp","turns:turn.example:5349"]
MOSAIQUE_WEBRTC_TURN_SHARED_SECRET=<protected coturn REST secret>
MOSAIQUE_WEBRTC_ICE_CREDENTIAL_TTL_S=3600
```

coturn deployment, TLS certificates, public/private address mapping, relay
range, firewall rules and forced-TURN validation remain R6/R7 work. No TURN
server, cloud resource, GPU or cross-network browser call was provisioned by
this PR.

## Validation and limits

The focused transport contract tests cover versioned signal validation,
meeting-scoped target routing and the all-peer flush barrier. Frontend
typecheck and the existing 99 unit tests pass; backend targeted tests and
ruff/format pass. OpenAPI was regenerated and contains the ICE route.

This PR does not claim audible end-to-end voice, NAT traversal, TURN relay,
two-stream Rust ASR concurrency, GPU behavior, or cross-network acceptance.
Those require real browsers, a configured TURN service and the later deployed
acceptance run. WebRTC signaling is intentionally tested separately from fake
ASR; fake transcription cannot establish media or model concurrency.

Rollback is application-only: deploy the R4 app/frontend together and remove
the optional WebRTC settings. No migration is required and existing meetings,
participants, recordings and transcripts remain readable. Clients that do not
understand the new messages retain the existing PCM transcription behavior.
