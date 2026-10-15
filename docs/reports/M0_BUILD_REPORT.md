# Builder Milestone Report — M0 architecture discovery only

Historical report for d8204d4. See [M0 review fixes](M0_FIX_REPORT.md) for the
corrected proposal and new verification. The missing fixtures below were deleted
by 7412d8d relative to main 6e9e85bd3806cf7f5c0205ece97e285f8d62da9e: this was
a regression within the reviewed branch, not an inherited main defect. They are
restored during M0 re-review rather than deferred to M1.

- Branch / commit / base: `codex/m0-architecture`; this documentation commit;
  inspected/tested application base `7412d8d9b6cc66f928d4cf01a57d2a65b20127fb`.
  Exact resulting documentation SHA is supplied in the final handoff and obtainable
  with `git log -1 --format=%H -- docs/reports/M0_BUILD_REPORT.md`.
- Date/environment: 2026-10-15, local macOS, existing Python 3.12 virtualenv and
  frontend node_modules; no dependency resolution/installation performed.
- Acceptance IDs in scope: AUTH-01..04, MEET-01..02, ASR-01..04, HIST-01,
  AI-01..02, INT-01..03, OPS-01..03 — **planning/mapping only**.
- Status: **PARTIAL** at the milestone gate: builder discovery/planning delivered;
  independent review and explicit human architecture approval pending. No enterprise
  acceptance completion claimed. Baseline verification is not fully green.

## User-visible behavior actually demonstrated

No new application behavior. Existing frontend unit tests/typecheck/build ran;
backend CPU tests and checks ran with failures reported below. No browser E2E,
real PostgreSQL, LiveKit, GPU or external-ticket workflow was demonstrated.

## Existing code reused, replaced and removed

Application source, migrations and dependency locks are unchanged. Nothing removed
by this work. The [inventory/matrix](../M0_DISCOVERY.md) identifies exact modules
and replacement gates. Preserve history, original transcripts, corrections,
evidence navigation, optional playback, meeting controls and lifecycle regressions.
Replace legacy auth/media/ASR incrementally only after approved parity work.

Pre-existing unstaged deletions were present at entry and deliberately excluded:
`CLAUDE.md`, `CODEX_HANDOFF.md`, `PROJECT_STATE.md`, `README.md`,
`infra/azure/.gitignore`, `infra/azure/check-parameters.py`,
`infra/azure/main.bicep`, `infra/azure/main.bicepparam.example`.
Frontend build changed tracked tsconfig.tsbuildinfo; restored only that generated
file to its unchanged entry/HEAD content. Build output is not part of the commit.

## Architecture and invariants

- Module boundaries and state owner: [design](../M0_DESIGN.md). Modular monolith;
  identity/workspaces, meetings, transcripts, intelligence/review, integrations.
  Separate worker process lifecycle and isolated participant STT sessions.
- New abstractions: admission/generation binding hides media identity and lifecycle;
  transcript events/revisions hide idempotency and provenance; approved commands
  hide provider uncertainty. These are proposals, not code or generic frameworks.
- Migration considerations: [expand/backfill/cutover plan](../M0_MIGRATION.md).
  Keep all IDs and raw text, never reset databases or auto-merge emails. Current
  integration test fixture drops tables; it was not run against an unknown DB.
- Major trade-offs: proven OIDC provider adds dependency; separate media lifecycle
  requires fencing; coarse Voxtral timing limits word-level UI; conservative
  ambiguous-write handling may require manual reconciliation.
- Proposed ADRs: [monolith/media](../decisions/M0-001-modular-monolith.md),
  [identity/migration](../decisions/M0-002-identity-and-migration.md),
  [reviewed actions](../decisions/M0-003-reviewed-actions.md).

## Verification (real commands and outputs)

Commands below run from backend or frontend as indicated. Results are observations
from this task, not claims about a clean CI installation.

| Check | Command | Result | Evidence |
|---|---|---|---|
| Backend unit initial sandbox run | backend: `.venv/bin/pytest tests/unit -q` | FAIL | 322 passed, 17 failed, 9 skipped; 13 missing-fixture failures and 4 localhost-bind permission failures |
| Diagnose socket failure | backend: `.venv/bin/pytest tests/unit/test_moshi_ws_transport.py -q -x` | BLOCKED by sandbox | PermissionError binding 127.0.0.1 |
| Socket tests with approved escalation | backend: `.venv/bin/pytest tests/unit/test_moshi_ws_transport.py -q` | PASS | 4 passed in 0.15s |
| Full unit rerun with sockets allowed | backend: `.venv/bin/pytest tests/unit -q -rs` | FAIL | 326 passed, 13 failed, 9 skipped in 1.63s; 11 failures in test_measured_timing and 2 in test_prompt_budget; missing b1-report.json / slice4-last-test-report.json; skips from same missing reports |
| Python lint | backend: `.venv/bin/ruff check .` | PASS | All checks passed |
| Python types | backend: `.venv/bin/mypy` | FAIL | 8 attribute/export errors in speech/adapters/kyutai/mlx_runtime.py; 101 files checked |
| Frontend tests/contrast | frontend: `npm test` | PASS with known contrast exclusions | 115 tests / 15 files pass; 43 contrast pairs pass, 3 known gap entries reported |
| Frontend types | frontend: `npm run typecheck` | PASS | tsc --noEmit exit 0 |
| Frontend lint | frontend: `npm run lint` | FAIL | eslint: command not found; not declared in package devDependencies |
| Frontend build | frontend: `npm run build` | PASS | TypeScript + Vite6.4.3, 51 modules transformed |
| PostgreSQL integration/realtime and slow suites | See proposed CI commands in migration plan | NOT RUN | No disposable DB provisioned/validated; destructive test fixtures excluded |
| Browser E2E | `npm run test:e2e` | NOT RUN | No app/DB/browser test stack started |
| Upstream/reference review | Read public source/docs; local reference git rev-parse + selected source reads | PASS as inspection only | Source links and exact local SHA in discovery; no dependency compatibility runtime proof |
| Documentation whitespace/scope | `git diff --check`; staged path/source diff inspection | PASS | Only planning Markdown staged; existing deletions excluded |

The initial shell inventory also hit a missing `.github/workflows/*` glob; explicit
file enumeration confirmed no workflow. This was not a CI success. Tests were not
added for a docs-only change; the plan specifies behavioral/negative/cleanup tests
for every implementation milestone. Missing fixtures were not copied from private
recordings, and source failures were not fixed outside M0 scope.

## External systems

- Real or mock? Existing deterministic tests only; localhost WebSocket fake peer
  exercised real local socket transport. No LiveKit/Modal/vLLM/Linear calls made.
- Public upstream documentation/source fetched read-only. Local old Voxtral source
  inspected read-only at `3dd4f96e22bf147a129e63b62f4fc18053458d1d`.
- GPU cost, permissions and actual measurements: **none incurred, NOT RUN**.
  Historical GPU logs in MODAL_REFERENCE are inherited evidence, not current
  measurements. The 1/2/4-stream experiment and budget gate are in discovery.

## Remaining risk and unverified acceptance

All enterprise criteria remain unverified; see the acceptance snapshot and
[threat model/open decisions](../M0_THREATS.md). Highest risks: Pipecat release/main
differences in resampling and bot publishing; vLLM rotation/timing/KV/concurrency;
tenant migration and revocation races; provider ambiguous writes. Exact compatible
Pipecat/LiveKit pins remain a gated M2 research task, not an invented version claim.
Baseline failures prevent claiming a green implementation/release gate.

## Reviewer handoff

- Exact commit SHA: final handoff identifies this report's commit; inspect that
  SHA rather than relying on a moving branch. Tested application SHA is above.
- Highest-risk documents: M0_DESIGN.md media/revisions/approval; M0_DISCOVERY.md
  version evidence/benchmark; M0_MIGRATION.md identity backfill and rollback.
- Independently check private-meeting access vs legacy org-wide host policy,
  composite tenant constraints, refreshed-token removal race, multi-device/track
  replacement, per-user resampling before routing, queues outside our adapter,
  uncertain time alignment, approval invalidation and ambiguous write recovery.
- Review questions: accept Auth0 and Linear as first providers? Accept coarse
  timestamp windows pending measurements? Are proposed module boundaries and
  compatibility migration minimal? What pilot retention/region and test budget
  should later be approved? Does runtime research justify proceeding to M1 while
  M2 remains gated?
- Independent reviewer findings: **not yet available**; none represented as
  resolved. Human approval: **pending**. Stop here; no M1 work, merge or deployment.
