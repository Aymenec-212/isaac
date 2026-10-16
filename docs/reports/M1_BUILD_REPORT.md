# M1 builder report — workspace persistence increment

- Date/environment: 16 October 2026; Darwin 23.3.0 arm64, Python 3.12, restricted local sandbox.
- Branch: `codex/m1-saas`.
- Base/tested HEAD: `b835059f3fcac01637a5f5f0229a885cb5ba1e03` plus **unstaged workspace changes**. There is no implementation commit.
- Status: **PARTIAL — M1 is not done.** Only the application-owned workspace persistence/authorization increment is implemented. No later milestone is started.
- Acceptance scope: supporting domain behavior for AUTH-02, AUTH-03, AUTH-04. No complete acceptance criterion is verified.
- Human steering approves Auth0/OIDC/PKCE and backend-owned tenancy. This increment introduces no password system, provider adapter, credentials, deployment or provider-resource provisioning.

## Observed behavior and boundary

Fourteen deterministic workspace tests demonstrate creation, rename, listing/switching and reload through independent database sessions; invitation verified-address binding, expiry, hashing and single use; role enforcement, cross-tenant denial, revocation, outstanding-invitation invalidation and last-active-owner protection. They also exercise disabled accounts, rollback, identity uniqueness and a composite inviter-membership foreign key. Equal email addresses never claim or merge accounts/history.

`Workspaces` owns authorization, membership mutations and invitation redemption. Its caller owns the SQLAlchemy transaction; async callers can use `AsyncSession.run_sync`. Organization row locks serialize mutations on PostgreSQL **by design; actual concurrent PostgreSQL behavior is unverified**. An authenticated server session must supply the account ID. Request bodies, provider role/org claims and legacy bearer tokens must never supply that authority.

The module has no HTTP/provider SDK imports. Architecture tests enforce that boundary. No HTTP route, browser login, session issuer or account provisioning adapter exposes this module yet. This is a backend increment, not a demonstrated account/workspace user journey. Existing prototype routes, authentication, media and UI remain in place and do **not** acquire enterprise security from these additions.

## Schema and migration

Added `accounts`, `memberships`, `workspace_invitations`, and additive Alembic revision `0004`. Accounts are global and uniquely keyed by issuer+subject. Memberships have an organization/account composite key. Invitations reference the inviter's membership in that same organization and store a SHA-256 hash of a 256-bit random token. Invitations expire after seven days and grant member role only. Owners assign roles/revoke; owner/admin can rename and invite. Address comparison trims and case-folds both addresses; it does not merge accounts.

No existing migration, legacy table, user, meeting, transcript, correction or identifier is changed or backfilled. No legacy identity mapping is automatically inferred. Downgrade explicitly refuses data deletion; application rollback must retain the additive schema. This is not authorization to run a real migration.

The SQLite test executes the actual `0004.upgrade`, compares its schema with the models and preserves an existing organization. Offline PostgreSQL SQL generation succeeds. A separate PostgreSQL rehearsal applies actual `0001`–`0004` operations in an isolated, rollback-only schema; its fixture includes raw transcript words/corrections and checks legacy row preservation and workspace reload. That rehearsal could not execute here. It does not use `metadata.create_all` as migration evidence. Backup/restore, production locking, migration timing and concurrent redemption/revocation remain unverified.

## Exact verification

Backend commands run in `backend/` using existing `.venv`; frontend commands run in `frontend/`. No dependency synchronization was claimed. Full command outputs remain locally at `/tmp/mosaique-m1-evidence/`.

| Command | Exact result |
|---|---|
| `.venv/bin/ruff check .` | PASS: `All checks passed!` |
| `.venv/bin/pytest tests/unit/test_workspaces.py tests/unit/test_architecture.py -q` | PASS: `33 passed in 0.75s` |
| `.venv/bin/pytest tests/unit -q -rs` (final) | FAIL: `4 failed, 367 passed in 1.86s`; all four failures attempt loopback socket binding, denied with `PermissionError: [Errno 1] ... operation not permitted` |
| Same unit command against a temporary copy of HEAD source/tests and repository fixtures | FAIL: `4 failed, 351 passed in 1.77s`; same socket-bind failures. Sixteen additional passing cases in final tree are fourteen workspace cases plus two architecture cases. |
| `.venv/bin/mypy` (baseline) | FAIL: `Found 8 errors in 1 file (checked 101 source files)` |
| `.venv/bin/mypy` (final) | FAIL: `Found 8 errors in 1 file (checked 105 source files)`; same eight diagnostics; no new source errors |
| `.venv/bin/pytest tests/integration/test_workspace_migration.py -q -rs` | FAIL at PostgreSQL connection: `1 failed in 0.69s`, `psycopg.OperationalError`, loopback connections denied with `Operation not permitted`. No migration behavior verified by this attempt. |
| `MOSAIQUE_DATABASE_URL=postgresql+asyncpg://mosaique:mosaique@localhost:5432/mosaique_test MOSAIQUE_TOKEN_SECRET=local-migration-test-secret-32-chars .venv/bin/alembic upgrade head --sql` | PASS, exit 0; generated PostgreSQL SQL through `0004`, without connecting to a database. The inline signing value is a dummy local test value. |
| `npm run typecheck` | PASS, exit 0 |
| `npm test` | PASS, contrast check and Vitest: `15 passed` files, `115 passed` tests |
| `npm run build` | PASS, exit 0; TypeScript and Vite production bundle |
| `npm run lint` (baseline; frontend unchanged) | FAIL, exit 127: `sh: eslint: command not found` |
| `git diff --check` | PASS, exit 0 |
| Other PostgreSQL integration/realtime suites; Playwright/browser E2E; real Auth0 | NOT RUN; required environment unavailable and no new public/browser path implemented. No hidden test skips added. |

The mypy diagnostics are pre-existing in `speech/adapters/kyutai/mlx_runtime.py`: `LmConfig` (136), `Lm` (137), `quantize` (140, 142), `mimi_202407` (149), `LmGen` (285), `Sampler` (288, 291). Ruff passed before implementation. Frontend ESLint is a pre-existing missing tool, not a newly introduced lint failure.

Baseline reproduction initially omitted repository fixture docs, causing unrelated missing-fixture failures/skips. After copying the fixtures with the correct repository layout, the baseline result is the four-failure/351-pass result above. The initial incomplete reproduction is not evidence of repository regressions.

Environment attempts: local PostgreSQL initialization failed at `shmget` with `Operation not permitted`; no test server was created. `uv add`/`uv lock` failed with a macOS `system-configuration` NULL-object panic, including offline attempts. A temporary pip tooling-install attempt failed DNS resolution. Dependency-file edits from those attempts were reverted exactly; no new dependency or lockfile change remains. These are environment constraints, not unresolved product decisions.

## Outstanding M1 work and acceptance limits

- AUTH-01: Auth0 integration, validated OIDC issuer/audience/signature/state/nonce/redirect, browser PKCE, registration/recovery/profile flows, opaque persisted cookie sessions, rotation, idle/absolute expiry, CSRF, logout/revocation and real two-account E2E are absent. Auth0 integration is **not verified** and is not represented by the local account fixtures.
- AUTH-02: actual authenticated HTTP and account/workspace UI, invitation acceptance journey and browser persistence are absent. Only domain behavior is implemented/tested.
- AUTH-03: full API/WS/token/job isolation and enterprise meeting authorization are absent. Domain isolation tests do not prove these application surfaces. Current legacy tokens remain prototype-only authority.
- AUTH-04: workspace authorization rechecks revocation, including an already-open SQLAlchemy session; protected meeting access/token issuance/WS enforcement is absent. LiveKit revocation semantics remain the approved M2 gate; no media token is issued here.
- Core enterprise meeting schema/access scaffold, reviewed legacy mappings/backfill, real PostgreSQL persistence/concurrency/migration rehearsal, CI and lint/type baseline repairs remain M1 work.
- No live Auth0, LiveKit, Modal/vLLM, GPU, paid service or business-system call was made. No cost/performance claim.

## Review handoff

Highest-risk areas: `workspaces/service.py` invitation/role/revocation transactions, `persistence/models/identity.py` tenant constraints and `0004_workspace_identity.py` schema alignment. Independently check concurrent last-owner removal, invitation redemption racing revocation, inviter privilege removal/restoration, account-disable interactions, database transaction isolation and legacy preservation on PostgreSQL. Caller transactions must be short and must roll back after failure; no network call should run inside them.

Diff self-inspection found and fixed disabled-member revocation and old invitations reviving after inviter privilege restoration; tests cover both. This is builder inspection, **not independent review**. Independent review and human approval remain pending. No staging, commit, push, merge or deployment was performed; the orchestrator owns staging/commits after approval.
