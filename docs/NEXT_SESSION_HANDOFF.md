# Fresh-session handoff — 2026-09-13

The user explicitly requested a fresh session to continue the remaining work.
Work slice by slice: one self-contained, well-documented PR, maintainer review/merge,
then the next slice. Do not automatically merge. Ask for concrete missing access
or input when needed; Docker is now working and GitHub access is available.

## Start here

1. Read this file, PROJECT_STATE.md (header and §12), CLAUDE.md's decisions,
   docs/two-user-cloud-architecture.md (especially §§4, 7, 8), and the R2–R4 documents.
   Older single-user-first and WebRTC-exclusion instructions are superseded by
   the architecture amendment. Historical evidence is not current acceptance.
2. Inspect Git status and fetch origin. Check PR #23's actual state:
   https://github.com/Aymenec-212/isaac/pull/23
   R4 is open for review at handoff, not known merged. If still open, review it
   and prepare the bounded R5 plan; do not start the next implementation slice
   until merge. No need to redo already-passing tests without a change or concern.
3. After R4 merges, branch from updated main using codex/ and implement R5.
   Keep R6/R7 separate. Update PROJECT_STATE.md and explain each PR independently.

## Repository and completed slices

Repository: /Users/mac/isaac, remote git@github.com:Aymenec-212/isaac.git.
R2 merged PR #21, 61c9c49. R3 merged PR #22, 0fb1a8f.
R4 branch: codex/participant-identity-review, implementation commit 5be5ac6;
this handoff is a subsequent documentation commit on the same PR.

- R2: remote Rust moshi-server adapter, ready/flush and transport/probe tests.
  Read docs/r2-remote-asr.md if present; locate R2/runbook files by filename if needed.
- R3: per-participant ASR failure isolation, recording continues, fresh-session
  recovery and gaps, bounded ingress/fan-out, shared durable finalization,
  stranded intelligence-job recovery. docs/r3-failure-lifecycle.md is precise.
- R4: retry-safe joins, capture generations and socket ownership, guest HTTP
  credentials/reload/review/audio and owning-host mutations. Read
  docs/r4-identity-review.md for contracts, migration, rollback and limitations.

R4 adds migration 0003: nullable participant join_nonce_hash with meeting-scoped
uniqueness. Apply before backend; no user database has been migrated. Nonce is
not authentication. Credentials are tab sessionStorage with existing JWT expiry.
Fresh capture starts a new AudioSession under the same participant; reconnect
resumes only the matching capture. Replaced sockets cannot write or disconnect
successors. End-of-input handshake is still R5 work.

Browser tests found two real defects fixed in R4: detail returned an empty roster;
a guest missing completion could stay live after MEETING_NOT_LIVE. HTTP state
fallback now takes the guest to review. FAILED review remains explicitly incomplete.

## Remaining work and decisions already made

The goal is two remote people hearing each other inside Mosaïque, separate mic
streams into concurrent real Rust ASR, attributed transcript, then both reviewing
persisted transcript/intelligence. Direct WebRTC plus TURN carries voice; keep
existing PCM WebSocket and neutral StreamingRecognizer/KyutaiBackend seams.
Continue voice with a warning during ASR outages. Modular monolith; MLX remains
one-stream native development only. No new single-user polish on the critical path.

- R5: shared capture, authenticated signaling and ICE credentials, peer playback,
  TURN configuration, mute/leave/end including end-of-input coordination. Test
  two browser contexts, stale signaling/replacement and forced TURN. Fake ASR
  tests do not establish model concurrency. Use architecture §4's exact contracts.
- R6: app/Compose deployment repairs, durable mounts, TLS, limits, real provider
  config, bounded metrics and rollout runbook. Validate image startup/migration,
  persistence across recreation, auth/origin/admission and deployed smoke.
- R7: actual 30-minute cross-network meeting, two Rust streams, faults, evidence
  review and measured acceptance (§8). Fix demonstrated defects and document
  runtime/environment; do not close gates on fake or simulated results.

Azure was selected using available credit. Subscription reported Microsoft Azure
Sponsorship despite the stated free trial. West Europe/France Central quota queries
were empty; SKU visibility is not quota/allocation. France Central T4 was quoted
at $0.615/hour during R2 research, not a current guaranteed price. User approved
looking at other regions: France/Spain/Italy/Poland/Sweden were candidates. Resolve
quota/eligibility and review a region/cost amendment before provisioning. No GPU
or cloud resources were deployed. Real ready/flush, CUDA tails, interruption and
two-stream performance remain unverified. Four-user gate follows separately.

## Validation evidence and reproducible environment

R4: 450 backend tests passed, one slow deselected; accelerated-hour test passed
separately in 67.02 seconds. Six new identity integration tests rerun after roster
fix passed. Frontend 99 tests, typecheck/build, all 20 Chromium browser tests passed
(2.2 minutes). Ruff/check/format and OpenAPI comparison passed. Mypy has eight
pre-existing errors in unchanged mlx_runtime.py (101 source files checked).
Migration 0001→0003, downgrade 0002 and re-upgrade passed on isolated PostgreSQL 16.

Docker PostgreSQL 16-alpine was local-only port 55434, ephemeral container
mosaique-r4-test-db, no user volumes. Test DB mosaique_test and separate browser/
migration DB mosaique_migration. That container and our uvicorn/Vite servers
were stopped after validation. Earlier native PostgreSQL 14 R3 test server is
also stopped. Recreate isolated test resources as necessary; do not use user data.

Backend commands run from backend with UV_CACHE_DIR=/private/tmp/mosaique-uv and
uv run --no-sync. Explicit MOSAIQUE_ASR_RUNTIME=fake and MOSAIQUE_LLM_PROVIDER=fake
are essential: repository .env otherwise selects real providers. Set
MOSAIQUE_TEST_DATABASE_URL to isolated PostgreSQL for pytest; app uses
MOSAIQUE_DATABASE_URL. Never run concurrent pytest sessions against one test DB:
fixtures drop/truncate tables. Run pytest -q -m 'not slow', then -m slow separately.
Export schema with python tools/export_openapi.py and compare frontend/openapi.json.
Frontend: npm test -- --cache=false; npm run typecheck; npm run build.
Browser: seeded fake-provider backend on 8000 and Vite on 5173, host token through
MOSAIQUE_HOST_TOKEN, MOSAIQUE_BASE_URL=http://localhost:5173, then
npm run test:e2e -- --workers=1. Chromium override used:
/Users/mac/Library/Caches/ms-playwright/chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
Check installed paths rather than assuming this cache remains available.

Local scratch logs /private/tmp/mosaique-r4-{tests,slow,browsers}.log exist, but
committed documents are the durable evidence. Do not copy tokens from scratch
seed files into documentation or tool output. There is no CI; local checks matter.

## Workspace/access cautions

Pre-existing changes belong to the user and were excluded from R4:
D frontend/node_modules/.package-lock.json;
M frontend/node_modules/.vite/deps/_metadata.json;
M frontend/tsconfig.tsbuildinfo; untracked scripts/.
Do not clean, stage or overwrite them. A fresh worktree avoids these changes.

SSH git push works. gh CLI was unavailable; PRs were created using authenticated
GitHub in the Codex browser as Aymenec-212. Discover available tools/access in the
new session; no need to install a plugin just to create a PR. Git metadata/network
commands required sandbox escalation, which was approved. No secrets committed.

The new task should report what it learned and the next concrete action. If PR23
is not merged, surface that gate and its review findings, rather than assuming
that this delegation authorizes merging it. Once merged, continue R5 autonomously
within the agreed slice and produce a documented reviewable PR.
