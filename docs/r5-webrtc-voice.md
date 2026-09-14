# R5 — direct WebRTC voice

R4 is the baseline (`1e48a9a`, merged PR #23). This slice adds the browser
voice plane without changing the PCM WebSocket transcription path or the
`StreamingRecognizer` seam. Browser audio is sent directly between the two
participants when possible and through the configured TURN service otherwise.
The app-server carries only signaling and never receives conversational media.

## Contracts

`GET /meetings/{meeting_id}/ice-config` requires an admitted meeting-scoped
participant credential and a LIVE meeting (a host account token alone is not
enough). Responses are `Cache-Control: no-store`. It returns configured STUN URLs and,
when TURN is configured, a coturn REST credential:

```json
{
  "ice_servers": [{"urls": ["turn:turn.example:3478"], "username": "<expiry>:<random>", "credential": "<hmac-sha1>"}],
  "expires_at": "<UTC timestamp>",
  "ice_transport_policy": "all"
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
`from_participant_id`. Voice-capable clients advertise `hello.client.voice=true`.
`hello.ok.connection_id` and `rtc.peers` supply socket generations. Each signal
must carry `connection_id`, `target_connection_id`, and `negotiation_id`.
Both socket generations are checked at delivery. A sender cannot target itself.
SDP/candidate lengths and signaling frequency are bounded; ICE uses the explicit
`sdp_mid` / `sdp_m_line_index` wire fields.

`audio.flush` carries the sender's last sequence and optional end `request_id`.
The gateway validates the accepted sequence before sealing further audio and
returning the matching `audio.flush.ok`. When the host calls end, the server sends
`meeting.end_requested` with a request ID, waits up to two seconds for connected
voice-capable participants to acknowledge, then enters the runtime drain.
Concurrent end calls share one task, request and remaining drain budget.
The deadline is shared; a missing peer is logged as incomplete and does not
hold finalization open indefinitely.

## Browser behavior

`MicrophoneCapture` exposes the one acquired `MediaStream` to both consumers:
the existing 24 kHz PCM worklet and `WebRTCVoice`. A deterministic participant
ordering chooses the offerer, preventing simultaneous negotiation glare. ICE
candidates are bounded and queued until the matching peer description exists.
Negotiation is serialized and waits for ICE configuration, supports streamless
remote tracks, and retries with fresh negotiations at most twice before failing.
Reconnect/replacement invalidates stale work. Mute disables the
track and suppresses PCM frames together; remote playback remains active.

Leave closes the peer, flushes the padded partial worklet frame, then seals and
closes the transcription socket. Host end uses the server handshake to stop both
participants' media and flush input. Late microphone permission after teardown
cannot retain live tracks.
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

Production coturn deployment, TLS certificates, public/private address mapping,
and firewall rules remain R6/R7 work. A local bounded-port coturn configuration
and forced-relay browser gate are in [deploy/turn](../deploy/turn/README.md).
That local gate passed on 2026-09-14. Only isolated local test containers were
started; no cloud resource, GPU or cross-network call was provisioned by this PR.

## Validation and limits

Completion follow-up on 2026-09-14, based on merged PR #25 (`2887460`):

- Backend: **462 passed**, one slow test deselected; separate accelerated-hour
  regression **1 passed**. Isolated PostgreSQL 16, fake ASR/LLM.
- Frontend: **115 unit tests passed**, production build passed. Backend
  ruff/format and mypy (91 source files) passed. OpenAPI/types regenerated.
- Entire browser suite: **22 passed**. Direct R5 scenarios separately repeated
  twice: **4 passed**. Forced-TURN scenarios: **2 passed**.
- Native Chromium 153 on macOS, two isolated contexts, fake microphones, real
  RTCPeerConnection and coturn 4.6.3. Assertions cover increasing bidirectional
  RTP, playback, mute, reload, leave/end track cleanup, and selected local AND
  remote relay candidates (not merely candidate gathering).

The browser gate caught and drove a fix for one-way audio: answerers must attach
capture to the offered transceiver, not a pre-created unnegotiated audio m-line.
The local TURN image requires NET_BIND_SERVICE in its capability bounding set
for its file-capability-bearing executable to start.

These gates establish local media flow and relay operation, not acoustic quality,
cross-network/NAT acceptance, TURN/TLS under blocked UDP, real two-stream Rust ASR
concurrency, or GPU behavior. Those remain deployed R6/R7 gates. Fake transcription
cannot establish model concurrency. R5 is ready for maintainer review, not auto-merge.

Rollback is application-only: deploy the R4 app/frontend together and remove
the optional WebRTC settings. No migration is required and existing meetings,
participants, recordings and transcripts remain readable. Clients that do not
understand the new messages retain the existing PCM transcription behavior.
