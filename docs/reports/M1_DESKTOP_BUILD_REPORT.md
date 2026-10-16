# M1 Desktop build report — enterprise SaaS foundation

- Date: 16 October 2026. Branch: `codex/m1-saas-desktop`.
- Original implementation commit: `1821d4fe9d4924b7f21340c55183bdb5d4aaf9a6`.
- Starting checkout: `5fbe92b7c8fb241ab020f1196afa646d583991a3` (`codex/m1-saas`).
- Approved M0/main: `51165577958dbedca74e14067bf9e1c6b31ff324`, unchanged.
- Status: **Independent review returned CHANGES REQUIRED. Focused remediation is submitted for re-review; complete M1 acceptance remains unverified. Not approved for merge or pilot operation.**
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

The original 58-file implementation manifest is in [M1_DESKTOP_FILES.txt](M1_DESKTOP_FILES.txt).
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
removes explicit grants. The first review identified that implicit organizer authority
was still revived by re-invitation; the remediation below corrects that defect. Domain owners
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
5. Organizer transfer and implicit administrative private access remain absent.
   The approved remediation policy adds explicit, audited owner restoration of the
   original organizer; re-invitation alone restores no meeting authority. Lists expose
   the latest 100 records; pagination/export, retention/deletion, operational cleanup
   and broader security hardening remain limitations, detailed in the operations guide.
6. Baseline prototype ASR failure, dependency advisories and absent live acceptance
   preclude a green release/readiness claim. Independent review returned the three findings addressed below; re-review and human approval remain required.

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

The original self-inspection did not catch local logout/callback races or implicit
organizer revival. Its provider-SID fencing and explicit-grant tests were insufficient
for those cases. See the focused remediation evidence below. Human approval remains
required before merge.


## Independent-review remediation — 16 October 2026

Review baseline: `b733e1567fb43bd2a6b47d2946cd8018d774d030`, clean working tree.
The commit containing this report is the remediation review target. The original
implementation/evidence above remains historical; the findings and results in this
section supersede its incomplete logout and organizer-revocation claims.
Scope: AUTH-01, AUTH-03/04, OPS-02. No M2 or deployment behavior is implemented.

| Verified finding | Status and affected files | Regression evidence / limitations |
|---|---|---|
| P1 local logout / logout-all versus OIDC callback | Fixed locally: `identity/sessions.py`, `app/auth/oidc.py`, `app/api/saas.py`, identity models, revision `0006` | Before changes, both exchange-paused endpoint tests failed (late callback 303 after logout 200). Final deterministic event-driven tests cover both endpoints during exchange, immediately before atomic validation, and immediately before session insertion while locks are held. They also cover another anonymous browser on logout-all and a legitimate new login while an old cancelled exchange remains in flight. No sleeps or process-local production locks. Live Auth0 remains unverified. |
| P2 missing offline deployment validator | Fixed: restored `infra/azure/check-parameters.py` byte-for-byte from approved main `5116557`; scope documented in adjacent README; `.github/workflows/verify.yml` now runs retained offline tests | Before restoration, unittest import failed with FileNotFoundError. After restoration all 5 cases pass. Original validator uses stdlib and ARM parameter JSON only; deleted VM templates/Bicep examples are not dependencies and remain retired. No Azure call/deployment. |
| P2 organizer authority revives after removal/re-invitation | Fixed locally: `workspaces/service.py`, `meetings/service.py`, meeting model, revision `0006`, SaaS restoration route and generated enterprise API contract | HTTP regression covers removal, re-invitation, list/detail denial, access-list and grant-management denial, forbidden self-restoration, explicit owner restoration and audit. Existing explicit-grant regression still passes. No owner private-visibility bypass or ownership transfer. |

### Boundary decisions and self-review

`Sessions` owns login start/completion/cancellation. A durable browser row records
its generation; login attempts capture that generation and a database sequence
value. Logout increments the browser generation and revokes all its sessions.
Logout-all additionally advances the account's sequence floor and revokes all
account sessions. This also cancels older anonymous attempts in other browsers
whose stable provider identity was not yet known when they began. New attempts
receive a later sequence value and remain legitimate.

Completion locks the stable issuer/subject, then the browser row, and checks both
generations, account state, provider SID tombstone and deadline before issuing a
session in the same transaction. Logout uses the same lock order. If completion
wins, logout waits and revokes its issued session before acknowledging success.
Logout authentication validates CSRF/expiry without first taking a session-row
write lock, avoiding reversed lock order. Rotation and provider logout retain
revoked session rows so the browser binding survives issuance races; authentication
rejects those rows. No database transaction spans provider network I/O.

Membership removal stamps `Meeting.organizer_revoked_at` and removes explicit
access grants under the existing workspace lock. List/detail/management share the
organizer authority predicate. Rejoining clears membership revocation only.
`restore-organizer` requires an enabled owner and an enabled active membership for
the original organizer, and writes an audit event. It neither transfers ownership
nor makes private records visible to owners implicitly. This small explicit action
implements the user's restoration policy without a new role/permission framework.

Revision `0006` is additive, preserves existing sessions and legacy content, cancels
pre-upgrade pending attempts, and backfills organizer revocations from both current
membership revocation and prior `membership.revoked` audit history (including an
already-reinvited member). A synthetic real-migration test verifies these cases and
an empty model/schema diff. Existing revisions are unchanged. Mixed-version writers,
operational lock timing and rollback remain separate gates; drain old processes.
Cancellation state cleanup is deliberately not improvised: retain browser/session
bindings while any associated session or callback could be valid; review retention
before operating at scale. See [operations](../M1_OPERATIONS.md).

Self-review inspected the complete remediation diff for domain/HTTP boundaries,
lock ordering, grant-rule duplication, legacy preservation and unrelated ASR changes.
There is one identity cancellation owner and one organizer authority predicate;
no provider domain, generic authorization framework or media behavior was added.

### Remediation verification

All PostgreSQL evidence uses the disposable local PG **14.19** instance on port
55432, Python 3.12.9 and synthetic data. Local logs:
`/tmp/mosaique-m1-remediation/`. These are local checks, not hosted CI evidence.
Backend/database-mutating browser checks run sequentially.

| Command / check | Actual result |
|---|---|
| `pytest tests/integration/test_workspace_migration.py tests/integration/test_oidc.py tests/integration/test_saas_foundation.py tests/unit/test_workspaces.py -q -rs` | **43 passed**, one existing Authlib deprecation warning, 3.54s |
| `pytest tests/unit tests/integration tests/realtime -q -rs` | **524 passed, 1 failed, 1 skipped, 1 deselected**, one warning, 102.55s. Only failure is the independently established silent-participant baseline. This sweep predates the final two additional new-login/old-exchange tests; the final targeted run includes both. |
| `.venv/bin/ruff check .` / `.venv/bin/mypy` | PASS / PASS, **116 source files** |
| Root `backend/.venv/bin/python -m unittest discover -s deploy/asr -p 'test_*.py' -v` | **5 passed** (0.006s); now explicitly included in backend CI job |
| `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` | PASS; **15 files / 115 unit tests**; contrast checker retains the same 3 documented gaps |
| Enterprise OpenAPI export and `npm run generate:saas-api` | PASS; regenerated 24-path contract adds only explicit organizer restoration. Fresh exports of both enterprise and 13-path prototype contracts match tracked files. |
| Fresh disposable UTF-8 DB: `.venv/bin/alembic upgrade head` / `.venv/bin/alembic check` | PASS, actual 0001→0006 chain / no new upgrade operations detected |
| `npm run test:e2e:saas` | **1 passed**, complete seeded two-account journey, 7.8s |
| `npm run test:e2e:prototype` | **28 passed**, all existing browser journeys, 2.2m |
| Final working-tree/diff inspection, `git diff --check`, retained validator comparison with approved main | PASS; only intended remediation files; no ASR changes; `main` unchanged |

### Baseline failure investigation and remaining gates

The unchanged prototype `_open_participant` in `realtime/sessions/meeting.py`
starts `_open_stream` on join. That creates audio metadata/file state and launches
`_pump`, which opens the recognizer before the first frame. This explains the
silent-participant assertion. Deferring that lifecycle requires coordinated
reconnect/capture/idle-close and resource-cleanup verification; removing a line merely
to turn this focused M1 report green is not a safe authorization fix. No ASR source
or tests were changed, suppressed or excluded. The existing opt-in MLX skip and slow
deselection remain; no new skips. The initial restricted sandbox PostgreSQL attempt
failed on socket permission and was rerun with authorized local access; it is not
an application regression. A separate migration bootstrap initially used the
cluster's SQL-ASCII maintenance database, causing driver string decoding to fail;
creating an explicitly UTF-8 disposable database resolved it without application
changes. The real upgrade/check then passed.

The three reported findings are fixed in local tests and submitted for independent
re-review, **not** a declaration that M1 is complete. Live Auth0 hosted registration,
recovery/back-channel delivery and plan/residency authorization remain unverified.
Hosted CI/Linux/PG16, sanitized operational migration/backup/rollback rehearsal,
old-process draining and migration timing remain unverified. Existing dependency
advisories and baseline ASR failure remain. M2 media revocation/active-call expiry
remain future milestone gates. No external account, cost, live credentials, push,
merge or deployment occurred.

Reviewer focus: reproduce callback race tests in both lock orderings, inspect the
sequence/browser generation invariants and soft-revoked binding lifetime; inspect
removal/rejoin/restoration authorization and audit; rehearse `0006` against reviewed
historical data; verify retained offline dependency and CI command; distinguish local
PG14/mock-provider evidence from the outstanding external gates.
