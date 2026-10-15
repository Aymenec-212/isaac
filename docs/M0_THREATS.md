# M0 threat model and open decisions

Proposed controls, not a security certification. Assets: tenant transcripts/audio,
identity/session credentials, invitations, approvals, integration credentials and
external tickets. Threat actors include unauthenticated clients, malicious members,
compromised browsers, untrusted model output and compromised external services.

| Boundary / failure | Control and concrete negative test | IDs |
|---|---|---|
| Browser → identity/app | OIDC validation, cookie/CSRF/Origin protections, session revocation, rate limits; forged issuer/audience, invitation replay, session fixation, logout reuse | AUTH-01..04 |
| Tenant → DB/API/WS/search/audio | Mandatory active membership + meeting access; composite tenant FKs and scoped reads/writes; fuzz every parent ID, WS cursor and object key with other tenant IDs | AUTH-03, HIST-01, INT-03 |
| App → LiveKit | Server room/identity grants; no admin/browser secrets; explicit revoke cutoff and all admissions removed; race revoke/token issue, old/refreshed token reconnect | AUTH-04, MEET-01 |
| Organizer end → Cloud shutdown | Durable end operation closes admission before disconnect/revoke/delete; include unused identities, refresh/same-second races, room recreation and crash after each Cloud call; remain visibly FINALIZING until closure confirmed | MEET-01..02, AUTH-04, OPS-03 |
| LiveKit → media worker | Identity binding, microphone-only routing, generation fencing, independent resampling/VAD/STT; spoof metadata, overlap, duplicate device and stale republish callbacks | ASR-01..03 |
| Worker → gateway/GPU | TLS, short-lived header credential scoped to worker/meeting, key rotation, payload/time/rate limits, private loopback vLLM; unauthorized socket, oversized frame, expired credential and stalled consumer | ASR-02, INT-03, OPS-03 |
| Worker/job → DB | Leases and fencing, tenant binding from persisted job, reauthorization for privileged work, bounded retries; crash after lease expiry and stale worker writes | AUTH-03, ASR-03, OPS-03 |
| Transcript → model → reviewer | Treat speech as data, no tool credentials, validate structured evidence/owner/version, render escaped text; malicious spoken instructions, invalid IDs, unsupported deadline and stale snapshot | AI-01..02 |
| Reviewer → outbox → provider | Exact version/destination approval, atomic enqueue/audit, permission check at send, ambiguity reconciliation; parallel approval/send, timeout after successful create, revoked role | INT-01..02 |
| OAuth/provider → app | State bound to org/session, encrypted credentials and refresh serialization, minimal scopes, allowlisted destinations; callback tenant swap, connection rotation and secret-leak tests | INT-03 |
| Storage/logs/backups/processors | No raw audio default; opt-in recording and signed/scoped playback, scrub tokens/text, tenant-scoped deletion and processor inventory; deletion while extraction is running, expired link, log inspection | OPS-01 |
| Dependency failure/cost abuse | Admission caps, timeouts, visible gaps/unsaved states, fail-fast health and hard container/budget limits; GPU/DB loss and cancellation soak; no silent fake fallback | ASR-02..04, OPS-03 |

Proposed privacy defaults for review: disclose transcription before admission and
persist policy/version acknowledgement; recording off by default; 30-day transcript
retention unless pilot contract sets a different permitted period. No raw audio
sent to extraction provider: only necessary transcript/evidence. LiveKit and Modal
process live audio, identity provider handles account data, LLM sees transcript,
Linear receives only reviewed action content and evidence links (not full transcript).
No claim of end-to-end encryption: the worker must access plaintext audio.

Deletion first tombstones access and cancels/fences jobs, then removes transcripts,
derived outputs, objects and credentials with retries. Retain only minimal permitted
audit metadata; immutable means tamper-resistant during retention, not forever.
Backups expire on a documented schedule; restore must reapply deletion tombstones.
Account deletion need not erase other participants' meeting records automatically;
define pseudonymization and organization ownership policy with the pilot customer.
External tickets are separate copies: disclose their retention and make external
deletion an explicitly approved action, not an implicit cascading side effect.

## Research and human decisions, separately tracked

1. **M2 blocker:** which Pipecat release/commit contains isolated resampling and
   required lifecycle fixes? Verify track identity/generation, upstream queue
   bounds and subscribe-only operation before pinning a compatible bundle.
2. **M2 blocker:** vLLM long-session/context/KV behavior, rotation loss, sustained
   1/2/4-stream scheduling and latency. No GPU benchmark was run in M0.
3. **M2 closure blocker:** approve and qualify per-language WER/CER, maximum evidence
   window, timing error after mute/rejoin and finalization-delay thresholds using
   the [quality gates](M0_DISCOVERY.md#m2-transcript-quality-decision-gates-m0-r3).
   Unset or failed limits need a documented product decision before M2 can close;
   word alignment may require a separately justified process/protocol change.
4. **M1 approval:** Auth0 provider suitability, region/cost, session lifetime and
   private-meeting/administrator policy. App memberships remain locally authoritative.
5. **M4 blocker:** Linear OAuth installation privileges, destination feasibility,
   provider idempotency and reliable lookup after ambiguous create. No API guarantee
   is assumed from an undocumented header or client-supplied ID.
6. **Before pilot:** permitted regions/data processors, disclosure/consent wording,
   retention and recording requirements, backup schedule and deletion SLA. Legal
   applicability requires customer/legal review; M0 makes no compliance conclusion.
7. **Before any paid test:** exact monetary ceiling and resource authorization.
   Main/source inspection and historical logs are not authorization to deploy.
