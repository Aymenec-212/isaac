# M1 Desktop build report — enterprise SaaS foundation

- Date: 16 October 2026. Branch: `codex/m1-saas-desktop`.
- Implementation commit: `1821d4fe9d4924b7f21340c55183bdb5d4aaf9a6`.
- Starting checkout: `5fbe92b7c8fb241ab020f1196afa646d583991a3` (`codex/m1-saas`).
- Approved M0/main: `51165577958dbedca74e14067bf9e1c6b31ff324`, unchanged.
- Status: **Local implementation ready for independent review; complete M1 acceptance remains unverified. Not approved for merge or pilot operation.**
- Scope: AUTH-01..04, persistent meeting metadata/access scaffold, OPS-02 foundation.
  No M2 media, M3 intelligence, M4 integration or M5 release-readiness implementation.
- Environment: macOS arm64, Python 3.12.9, uv 0.9.26, Node 23.7.0, PostgreSQL **14.19**.
  PG16 is configured in CI but has not been run here.

## Demonstrated behavior and affected files

The starting checkout already contained the workspace persistence increment in
`5fbe92b`; the earlier assertion that no application changes existed was not true
of this repository. This implementation extends that code rather than replacing it.
Earlier documentation/infra deletions in the inherited history are not changes
introduced by this Builder. Review this implementation against `5fbe92b`; review
the complete milestone history separately against approved M0/main.

- Hosted identity adapter: `app/auth/oidc.py`; account mapping/profile and opaque
  sessions in `identity/`. Signed local OIDC tests prove issuer/audience/signature/
  nonce/PKCE checks, one-use browser-bound state, rotation, disabled-account denial,
  and equal-email identities remaining separate. Hosted registration/recovery are
  delegated to Auth0, not reimplemented in application password endpoints.
- `workspaces/service.py` now supports revocable invitation listing, durable audit,
  and removal of private-meeting grants on membership revocation. Existing last-owner,
  invitation expiry/address binding and multi-org behavior are retained.
- `meetings/service.py`, expanded existing `Meeting`, and `MeetingAccess` implement
  persisted private meeting preparation/list/detail/grant/revoke. An ordinary member
  may organize; only that organizer controls access. A workspace owner has no implicit
  private-meeting bypass. Foreign/missing grant targets return the same 404.
- `app/api/saas.py`, response schemas and shared dependencies expose real authenticated
  HTTP operations. Commit failure returns an error and rolls back before HTTP success.
  CSRF and exact Origin checks protect mutations. Session/identity responses are no-store.
- `app/main.py`, settings, health and legacy repositories enforce explicit process/
  meeting mode. Enterprise starts no prototype media/job loops and mounts no legacy
  bearer/guest/WS endpoints. Missing IdP configuration is actionable and unready.
- `frontend/src/saas/` implements profile, workspace create/switch/rename, member roles/
  revocation, manual invitation links/acceptance/revocation, meeting preparation/access,
  and audit display. Settings and meeting panels own their form state. Selected
  workspace survives reload and stale workspace reads are discarded. Session credentials
  never enter browser storage. Error/loading/empty states come from real requests.
- Revision `0005`, model constraints and migration tests preserve existing IDs,
  raw transcript words/corrections and legacy identities; no claim/backfill/reset is run.
- `.github/workflows/verify.yml`, lockfiles, ESLint configuration, direct MLX imports,
  API generation and browser configurations repair verification foundations. The MLX
  change fixes eight mypy re-export diagnostics without changing model behavior.
  `ReviewPage` receives a stable memo dependency to satisfy the restored lint gate.

The exact 58-file implementation manifest is in [M1_DESKTOP_FILES.txt](M1_DESKTOP_FILES.txt).
Generated API contracts and package locks account for much of the diff.

## Architectural decisions

Auth0 authenticates; PostgreSQL owns accounts, organizations, memberships, roles,
meeting access and sessions. Stable issuer/subject maps accounts; email never grants
legacy ownership or merges accounts. No Auth0 Organizations SDK/domain dependency.
Existing global accounts leave room for future restricted authenticated guests.

Authlib owns OIDC protocol/signature validation; PyJWT validates signed back-channel
logout. Browser cookies are opaque, host-only, HttpOnly, SameSite=Lax, Secure on HTTPS.
Pilot settings require HTTPS and reject prototype mode. Login state/nonce/verifier
remain in ten-minute database rows. Provider tokens are discarded; no offline scope,
refresh-token store, custom password cryptography, cache service or queue is introduced.

Application sessions expire after 30 minutes idle or 12 hours absolute. Authenticated
activity extends idle time only. Login rotates the old browser session; logout,
logout-all, disable and signed provider revocation remove authority. A stable identity
transaction advisory lock plus SID tombstone fences logout arriving before the first
account row or before an in-flight callback commits. No network call holds a DB transaction.

Workspace row locks serialize role changes, invitation redemption and meeting grants.
Composite tenant/parent constraints reinforce scoped application checks. Revocation
removes grants so re-invitation cannot revive private-meeting access. Domain owners
have no HTTP/provider SDK imports; import fitness tests cover these boundaries.

Existing meeting rows remain canonical. `mode` plus identity constraints distinguish
legacy hosts from enterprise organizers; there is no fallback after failed enterprise
authentication. Revisions 0001–0004 are unchanged. Downgrade refuses deletion; any
operational migration/rollback needs the separate reviewed rehearsal and mode-safe
application plan described in [operations](../M1_OPERATIONS.md).

## Executed verification

Backend commands use existing `.venv/`; locked dev, protocol and existing optional
MLX packages were synchronized. No weights, microphone recordings or live providers
were used. Test DSNs name disposable databases on local port 55432. Full logs are
local at `/tmp/mosaique-m1-desktop-evidence/` and are not committed.

| Check / command | Observed result |
|---|---|
| Backend `.venv/bin/ruff check .` | PASS, all checks passed |
| Backend `.venv/bin/mypy` | PASS, 115 source files |
| Focused final `pytest tests/integration/test_workspace_migration.py tests/integration/test_oidc.py tests/integration/test_saas_foundation.py tests/unit/test_identity_settings.py tests/unit/test_identity_logging.py -q -rs` | **29 passed**, one Authlib deprecation warning, 2.29s |
| Broad `pytest tests/unit tests/integration tests/realtime -q -rs` | **1 failed, 515 passed, 1 skipped, 1 deselected**, one warning, 102.56s. Last broad sweep precedes the final target-ID concealment tightening; the final focused run above tests that change. |
| Unchanged starting commit, same broad command, isolated copy/DB with corrected subprocess PYTHONPATH | **2 failed, 485 passed, 1 skipped, 1 deselected**, 101.14s |
| Actual migration 0001→0005 functions in rollback-only PG schema | PASS in focused suite: preserved legacy values including words/corrections; full model/schema comparison empty |
| Disposable `pg_dump -Fc`, new database, `pg_restore`, row-count/content-hash comparison | PASS: **17 tables match**, including 2 transcript segments, 2 audio-session metadata rows, meeting output and accounts. DB-only backup; audio/object storage recovery is not demonstrated. |
| Frontend `npm run lint`, `npm run typecheck`, `npm run build` | PASS |
| Frontend `npm test` | PASS: 15 files / **115 tests**; existing contrast script passes with its three explicitly reported known gaps |
| `npm run test:e2e:saas` | PASS: **1** complete two-account workspace/invitation/private-access/revocation/profile/logout browser journey, 7.0s on final transaction behavior |
| `npm run test:e2e:prototype` | PASS: **28** existing browser tests, 2.4m before the final transaction lifetime tightening |
| `npm run test:e2e:prototype -- e2e/meeting.spec.ts` after that tightening | PASS: **1** original create/join/transcribe/end/reload journey, 11.6s |
| Export enterprise OpenAPI to temporary file and `cmp` committed contract; regenerate both TS contracts | PASS; no legacy contract removal |
| `git diff --check`, staged diff inspection | PASS |
| `npm audit --package-lock-only --json`, current versus starting lockfile | Same **10** advisory packages and severity counts: 2 critical / 5 high / 3 moderate. Existing toolchain dependency risk, not newly introduced by ESLint; not remediated in this milestone. |
| GitHub Actions / Linux PG16 / real Auth0 / production migration | **NOT RUN**, no push/provider provisioning/operational data authorized |

### Baseline versus new failures

The remaining failure is
`tests/realtime/test_idle_and_pause.py::test_a_silent_participant_does_not_claim_the_recognizer_stream`:
the existing prototype opens a silent participant's ASR stream. It reproduces on
unchanged `5fbe92b`. No media-runtime implementation change was made to hide it.
CI deliberately continues to run that test and will be red until it is resolved.

The starting commit also failed its assertion that the entire schema still contains
only eight tables, despite its already-added 0004 identity tables. The assertion now
checks the full additive schema. Baseline missing ESLint and eight MLX mypy errors
are repaired. Four initial sandbox socket failures disappear with authorized local
socket execution; they are not application regressions.

An early browser attempt overlapped a database-mutating suite and was invalid;
sequential reruns pass. An early baseline subprocess imported the working tree;
corrected PYTHONPATH produces the two-failure comparison above. A broad run under
parallel load also observed a prototype final/gap timing assertion; isolated and
sequential reruns passed. These attempts are not presented as final new regressions.
The existing opt-in real MLX test remains skipped and the marked slow run excluded,
with no new skips or exclusions. Authlib emits a transport deprecation warning;
its supported successor has not been substituted speculatively.

## Acceptance limits and operational blockers

AUTH-01..04 remain **implemented/not verified** as complete criteria. Local SQL,
HTTP, cryptographic mock-provider and browser evidence proves their implemented
subfeatures, not a live enterprise rollout. OPS-02 is implemented/not verified
because hosted CI has not executed and the baseline regression remains red.

1. Auth0 plan suitability, region/residency/cost, approved credentials and real
   two-account registration/login/recovery/back-channel delivery remain gates.
   [Auth0 documents back-channel logout](https://auth0.com/docs/authenticate/login/logout/back-channel-logout)
   as an Enterprise-plan capability. No purchase/provisioning is authorized. If the
   plan is unsuitable, review an alternative event-delivery integration before rollout.
2. Password-recovery invalidation depends on configuring and verifying that event
   delivery. An outage can delay local revocation; no immediate-revocation claim.
3. Actual PG16/hosted CI and a sanitized operational legacy snapshot rehearsal,
   reviewed ownership mappings/backfill, migration lock timing and production
   rollback are unverified. Existing history is quarantined from new accounts.
4. LiveKit tokens/WS/media revocation and active-call expiry/rejoin are M2 gates.
   M1 has no call: the authenticated activity operation is tested, but M2 must drive
   it from actual participation so long speaking/listening does not look idle.
5. Private-meeting organizer transfer/admin access is not implemented; revoked
   organizers cannot regain access without an explicit later policy. Lists expose
   the latest 100 records; pagination/export, retention/deletion, operational cleanup
   and broader security hardening remain limitations, detailed in the operations guide.
6. Baseline prototype ASR failure, dependency advisories and absent live acceptance
   preclude a green release/readiness claim. No independent review has occurred.

No external account, paid resource, provider credential, real customer recording,
production migration, ticket write, push, merge or deployment was performed. The
local test cluster is stopped after verification; its disposable files/evidence
remain under `/tmp` for reproduction.

## Independent Reviewer handoff

Review implementation `1821d4f` against `5fbe92b`, plus inherited M1 changes against
M0/main. Highest-risk paths: OIDC state consumption and fixed redirects; SID/logout
races (including before first account); cookie/Origin/CSRF and expiry; tenant-safe
grant targets; workspace locks/last owner; invitation replay/revoke; composite FKs
and legacy preservation; commit-before-response failure handling; UI stale responses
and no credential storage. Reproduce real PostgreSQL tests, inspect CI rather than
assuming it ran, and keep provider mocks distinct from live Auth0 evidence.

Builder self-inspection fixed first-login/logout fencing, target-ID existence
leakage, grant revival on re-invite and commit acknowledgement timing. This is not
independent review. Human approval remains required before merge.
