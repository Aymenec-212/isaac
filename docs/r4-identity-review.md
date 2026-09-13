# R4 — stable participants and guest review

Baseline: merged R3, PR #22 (`0fb1a8f`). This slice preserves identity across
join retries, reloads and reconnects, and lets guests review their meeting without
a host login. It includes no WebRTC, TURN, GPU provisioning or region change.

## Behavior and contracts

Previously a retried join created another participant, a reload could restart
sequence zero in an old capture, and guest HTTP review relied on the global host
token. R4 separates participant identity, microphone capture and host authority.

The browser saves a random `join_nonce` in sessionStorage before submitting join.
The server validates the invitation and meeting state on every attempt, locks
the meeting row, then looks up the meeting-scoped nonce hash. Concurrent retries
return the same participant with a newly issued session token; the original name
and role remain stable. The nonce is not authentication and never bypasses the
invite or meeting state checks. It is optional for older clients, which retain
non-idempotent joins. Existing participants are not retrospectively deduplicated.

A successful join saves meeting-scoped credentials in the tab's sessionStorage.
Transcript, outputs and evidence audio use that credential. An unrelated global
host login cannot replace a guest credential. An owning host's saved credential
is used only while it matches the current host login; logout falls back to the
participant credential. Storage is per tab and tokens retain their existing
expiry: this is not cross-device identity, refresh-token issuance or durable
account recovery. Missing credentials require reopening the invitation.

The live route becomes `/meeting/{id}` after join. Reload restores the same
participant, obtains current meeting state, and hydrates persisted transcript.
Ended meetings open review. A reconnect rejected with `MEETING_NOT_LIVE` checks
HTTP state so a guest who missed the completion broadcast can still reach review.
The detail endpoint now returns the real participant roster.

`can_manage` is added to join/detail responses. Only an authenticated host whose
subject equals the meeting's `host_user_id` can end, correct or regenerate.
Participant tokens cannot create/list meetings or perform these mutations;
participant role alone never confers host authority. Existing organization host
read access remains. Guests can read only their authorized meeting and receive
read-only review controls. Authorization is enforced server-side, not just in UI.
OpenAPI and generated frontend declarations include the additive fields.

## Capture and socket ownership

`hello.capture_id` is optional for protocol compatibility. A MeetingClient creates
one random value and preserves it through socket reconnects; a reload creates a
new value. Matching captures resume sequence progress. A changed capture closes
the old audio/inference session and opens a fresh session at sequence zero under
the same participant. Legacy clients omitting the field retain prior behavior.

The gateway tracks the current socket owner separately from sendable sockets.
Replacement closes the old socket with bounded waits; old frames and its cleanup
cannot submit audio, remove the successor or mark it disconnected. Ownership is
checked after asynchronous setup and on each inbound message. The browser buffers
audio until `hello.ok` and ignores callbacks from superseded sockets.

This does not add R5's end-of-input handshake. Audio captured but not admitted
before finalization remains outside the existing drain boundary.

## Migration and rollback

Apply Alembic `upgrade head` before the new backend. Revision `0003` adds nullable
`participants.join_nonce_hash` and unique `(meeting_id, join_nonce_hash)` constraint.
Existing rows with null hashes remain valid. No token or audio rewrite occurs.

With active meetings stopped, roll back app/frontend together to R3 and run
`alembic downgrade 0002` if removing the schema addition is required. Downgrade
removes nonce hashes and retry deduplication history, but preserves participants,
transcript and audio. Re-upgrading cannot reconstruct removed nonce mappings.
No migration was run against user data during this slice.

## Validation

Docker PostgreSQL 16 ran on loopback port 55434 with isolated test and browser
migration databases, no user volumes. ASR and LLM were explicitly fake. Commands:

```sh
# backend/, with MOSAIQUE_ASR_RUNTIME=fake and MOSAIQUE_LLM_PROVIDER=fake
# MOSAIQUE_TEST_DATABASE_URL points to the isolated PostgreSQL 16 test database.
uv run --no-sync pytest -q -m 'not slow'
uv run --no-sync pytest -q -m slow
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
# Separate isolated migration database: upgrade head, downgrade 0002, upgrade head.
# frontend/
npm test -- --cache=false
npm run typecheck
npm run build
# Local seeded backend and Vite; host token supplied through test environment.
npm run test:e2e -- --workers=1
```

Results: **450 backend tests pass**, one slow deselected. The accelerated-hour
regression passes separately in **67.02 seconds**. The six new integration tests
also pass after the detail roster fix. **99 frontend tests** and typecheck/build
pass. **All 20 browser tests pass** (2.2 minutes) with Chromium and fake microphones.
Ruff and format pass. Mypy retains eight existing MLX dependency/type errors,
with no new errors (101 source files). OpenAPI export matches the committed copy.
Migration upgrade from 0001 through 0003, downgrade to 0002 and re-upgrade passed.

New tests exercise concurrent/lost-response joins, nonce scoping, guest HTTP
authorization, owning-host permissions, matching/fresh captures, stale socket
traffic, credential selection, handshake buffering and stale browser callbacks.
The browser gate joins host and guest, reloads the guest without a third participant,
ends the meeting, reloads guest review and fetches evidence audio without host login.
It exposed and verified fixes for the empty detail roster and missed-completion race.

Real Rust/CUDA recognition, two-stream performance, interruption recovery on GPU,
WebRTC voice and cross-network calling remain open. Azure quota and the reviewed
region amendment remain prerequisites to provisioning. Review/merge R4 before R5.
