# Incremental migration and implementation sequence

Proposal only; no database inspected, migrated or reset in M0.

## Expand, backfill, validate, cut over

1. Preserve Alembic `0001`–`0003` and all existing IDs. Rehearse from an empty
   disposable PG16 database and a sanitized snapshot at revision 0003. Backup and
   restore must be demonstrated before any real migration. Measure row counts,
   raw-text/word hashes, evidence links and referential consistency before/after.
2. M1 adds global accounts, external identities, memberships, invitations and
   sessions. Keep legacy `users` (currently tied to one organization) as historical
   identities; add explicit legacy-user → account mapping and nullable account
   references. Do not merge duplicate emails across tenants automatically. Claim
   mapping only through verified identity and reviewed ownership; unmapped history
   stays quarantined from new accounts. Backfill memberships in resumable batches.
3. Add meeting access, admission and audit records. Preserve legacy host/participant
   IDs and provenance. Disable legacy bearer/invite admission on enterprise routes;
   an imported guest is historical attribution, not a reusable credential. Run old
   and new paths under explicit meeting mode, never a fallback after auth failure.
4. Add composite org+parent constraints. First detect/quarantine inconsistent rows,
   then validate constraints; never silently move records between tenants. Build
   indexes with bounded lock time where appropriate. Persist migration checkpoints
   and run read comparisons before enforcing new non-null fields.
5. M2 adds room/admission/track/ASR generation metadata, worker leases and durable
   transcript events/gaps. Existing audio_sessions remain readable at 24 kHz;
   new sessions record actual 16 kHz format. Never reinterpret old sample counts.
   Persist final segments during M2; M3 is not permission to leave live data volatile.
6. M3 adds revision history and extraction snapshots. Import the existing raw final
   as revision zero and current correction as a legacy revision with its known
   actor/time; previous overwritten corrections cannot be reconstructed. Preserve
   raw text/words and IDs. Legacy outputs are unreviewed historical derivations,
   never implicitly approved. Backfill exact evidence references where possible;
   unresolved references block approval. Add leased job execution and snapshot keys.
7. M4 adds encrypted connections, versioned approvals, outbox commands and ticket
   links. No historical action is automatically dispatched. Create no external
   tickets during migration. M5 adds validated deletion/retention operations.

Use one canonical writer per meeting mode. Compatibility read projections may
translate schemas, but do not create two authoritative transcript stores. Rollback
means switching new admissions off and rolling application code back only while
schema compatibility holds; keep additive columns and data. No downgrade that
drops corrections/history. Contract/drop migrations require separate approval
after restore tests and a retention window. Avoid editing already-applied migrations.

## Ordered milestones and measured gates

Each row needs a report, independent review, no unresolved P0/P1 and human approval
before merge. Proposed numbers below are test targets, not measured outcomes.

| Slice | Acceptance IDs | Behavior, tests and exit condition |
|---|---|---|
| M0 architecture | All IDs mapped | Docs-only diff, reproducible baseline failures, proposed ADRs and explicit research gates; stop for review |
| M1a baseline + identity | AUTH-01, OPS-02 foundation | Repair missing sanitized fixtures, MLX type and frontend lint setup; establish actual CI. Two real accounts register/login/logout/recover; expired/wrong-issuer/forged sessions fail |
| M1b workspaces + migration | AUTH-02..04 | Two orgs and one user in both; invitation replay/expiry/address mismatch, last-owner and IDOR tests. Deny removed user on every application surface. Rehearse 0003 upgrade/backfill/rollback compatibility and preserve all history hashes. LiveKit revocation subcase remains deferred to M2 |
| M2a dependency/transport gate | MEET-01, ASR-01..02, AUTH-04 | Resolve Pipecat fixes and lock exact SDKs; CPU identity/queue/cancellation tests. Then two real accounts hear overlapping audio on LiveKit, mute/leave/republish, unauthorized token and refreshed-token revocation tests. No custom transport rewrite before upstream assessment |
| M2b transcript + inference | ASR-01..04, OPS-03 foundation | Durable finals/gaps and deterministic revisions/source-time tests; reject stale worker epochs. Execute 1/2/4 GPU experiment from discovery with approval. Report p50/p95, memory, drops, cold start and costs; zero unexplained attribution errors. Cannot close ASR-04 from fake tests |
| M3 history + intelligence | MEET-02, HIST-01, AI-01..02 | History after refresh/logout/restart; corrections/search preserve raw evidence; unsupported owner/deadline and prompt-injection fixtures; stale approval rejection. Kill/restart jobs between claim/provider/store and recover without duplicate durable outputs |
| M4 Linear vertical slice | INT-01..03 | Approved exact proposal creates one linked sandbox ticket. Double-click, parallel dispatch, revoke-before-send, token rotation and ambiguous provider timeout tests. Prove reconcile behavior or explicitly stop for manual reconciliation; no blind resend |
| M5 pilot readiness | OPS-01..03 + regression of all | Verify consent/retention/deletion including jobs, objects and backup policy; restore rehearsal, alert/incident runbooks, actionable degraded UI. All required CI and separately authorized live checks green; documented privacy/residency decisions and human pilot approval |

Privacy disclosure, tenant security and recoverability start with their first
affected feature; M5 validates them, rather than introducing them late. Once an
earlier slice becomes operational, it must not expose a later slice's unfinished
security boundary. Choose small commits inside milestones; no application work
is authorized by this M0 document alone.

## Actual tooling and proposed CI

Current backend: Python >=3.12, uv.lock, pytest/pytest-asyncio, Ruff, strict mypy,
SQLAlchemy/Alembic/asyncpg. Frontend: npm lock, React18/Vite6/TypeScript, Vitest,
Playwright; declared lint script without ESLint dependency/config. No CI workflow
found. Existing local dependencies were used; no environment sync was performed.

After M1 tooling repairs, proposed commands (not claims of success):

```sh
# backend directory; CI installs locked dev + remote-protocol extras
uv sync --frozen --extra dev --extra moshi-server
uv run --no-sync ruff check .
uv run --no-sync mypy
uv run --no-sync pytest tests/unit -q -rs
# Dedicated disposable PG16 service and explicit test DSN only:
uv run --no-sync pytest tests/integration tests/realtime -q -rs
# Separate deliberate long-run job (default pytest excludes slow):
uv run --no-sync pytest tests/realtime -m slow -q -rs
# frontend directory
npm ci
npm run lint
npm run typecheck
npm test
npm run build
npm run test:e2e
```

CI must provision a throwaway database and set both application/test DSNs, install
Playwright Chromium, start fixture backend with fake ASR/LLM plus frontend, wait
for readiness and always tear down. Inspect browser specs' environment expectations
before wiring the workflow. Add a distinct Alembic upgrade/backfill rehearsal;
current integration fixtures use metadata.create_all and cannot prove migrations.
Validate generated OpenAPI/TypeScript drift with existing export/generate tooling.
Keep Linux default install and optional macOS MLX compatibility separate, not
silenced by excluding a broken file. LiveKit/Modal/Linear real tests are separately
labeled, budgeted/on-demand checks, never implied by deterministic fake tests.
