# M1 local operation and identity gate

M1 implements AUTH-01..04 application foundations. It does not implement media
admission, transcription or meeting completion. See [build evidence](reports/M1_DESKTOP_BUILD_REPORT.md).

## Run locally

Use a **disposable local database** for verification. Never point the integration
suite at operational data: its fixtures recreate application tables.

```sh
# backend/
uv sync --frozen --extra dev --extra moshi-server
# Configure a local PostgreSQL DSN and a dummy prototype signing value >=32 chars.
# MOSAIQUE_DATABASE_URL=postgresql+asyncpg://.../mosaique_test
# MOSAIQUE_TOKEN_SECRET=... (prototype compatibility; never an OIDC credential)
uv run --no-sync alembic upgrade head
MOSAIQUE_APPLICATION_MODE=enterprise uv run --no-sync uvicorn mosaique.app.main:create_app --factory
# frontend/
npm ci
npm run dev
```

Enterprise is the default in both builds. The legacy prototype remains available
only with **both** `MOSAIQUE_APPLICATION_MODE=prototype` and
`VITE_APPLICATION_MODE=prototype` (restart Vite/rebuild). Pilot settings reject
prototype mode. Do not expose a prototype deployment as an enterprise application.
Legacy repositories filter out enterprise meetings; enterprise routes never accept
prototype credentials. Enterprise startup launches no legacy media or LLM workers.
Existing records/IDs/raw transcripts/corrections remain in their original tables.
There is no email claim, backfill, reset or automatic access to legacy history.
A reviewed legacy-account ownership/mapping process remains a separate gate before
importing operational history.

## Auth0 configuration — approval required before provisioning

No account, tenant, credentials or cloud resource was created by this work.
Configure a confidential regular web application with hosted registration/login
and password recovery, RS256 ID tokens, verified email and OIDC `sid` claims.
Mosaïque deliberately requires `sid` so provider revocation can identify sessions.
Use these settings through a secret manager; do not commit real values:

- `MOSAIQUE_PUBLIC_ORIGIN`: exact browser origin, without trailing slash/path;
  HTTPS is mandatory for `environment=pilot`.
- `MOSAIQUE_OIDC_ISSUER`: exact HTTPS tenant/custom-domain issuer with trailing `/`.
- `MOSAIQUE_OIDC_CLIENT_ID` and `MOSAIQUE_OIDC_CLIENT_SECRET`: backend only.
- Exact callback: `{PUBLIC_ORIGIN}/api/auth/callback`.
- Back-channel logout URI: `{PUBLIC_ORIGIN}/api/auth/backchannel-logout`.
- Select password-change, session revocation and relevant logout initiators in Auth0.
- Reverse proxy `/api/*` to backend `/*`; forward the original Origin. Apply request
  size and per-IP rate limits to auth endpoints. Restrict CORS to the browser origin.

[Auth0 documents back-channel logout](https://auth0.com/docs/authenticate/login/logout/back-channel-logout)
as an Enterprise-plan capability. Suitability, pricing, residency, delivery/retries
and the password-change initiator **must be verified with approved provisioning**.
If that plan is unsuitable, review the provider-event alternative before enabling
accounts; do not silently omit recovery revocation. This is an operational blocker,
not authorization to buy an Enterprise plan. Hosted recovery changes the provider
password; it is the validated logout event that ends local application sessions.
Provider events are eventually delivered, not synchronous password-change fencing.
A delivery outage can delay revocation; short local expiry bounds that exposure.

The adapter uses Authlib for authorization code/PKCE and ID-token validation, and
PyJWT for the signed logout token. Tokens are discarded after identity validation;
there is no refresh-token store or offline access. OIDC state/nonce/verifier stay in
a ten-minute PostgreSQL attempt row. Browser cookies contain random handles only.
Callback state is consumed before the token exchange; retry a failed exchange by
starting login again. Callback URLs are built from configured origin, never Host
headers or arbitrary return URLs. Access logs strip query strings; configure edge
logs likewise. Auth0 receives account data, not meetings/transcripts.

## Sessions and permissions

Host-only HttpOnly/SameSite=Lax cookies are Secure on HTTPS. HTTP is supported for
local development only; pilot validation requires HTTPS. Login rotates the browser's
old application session. Logout deletes that session; logout-all deletes all local
sessions. Subsequent login requests force provider reauthentication. Account disable
and membership changes are checked on every protected request. Signed back-channel
logout validates RS256, issuer, audience, expiry, recent issuance, SID, subject and
event type, removes matching sessions and leaves a SID tombstone. A PostgreSQL transaction advisory lock on the stable identity
serializes this against login so a late callback cannot resurrect a revoked SID.

Initial limits: **30-minute idle**, **12-hour absolute**. Successful protected requests
advance idle time; browser interactions send CSRF-protected activity at most every
five minutes. Merely leaving a background tab open does not keep it alive. Activity
never extends the absolute deadline. An expired request returns 401; UI asks for
sign-in and records already committed remain persisted. Unsaved form fields are
not promised to survive navigation. Invitation fragments are held in per-tab session
storage while signing in and cleared after acceptance; session credentials never
enter local/session storage.

M1 has no active calls. M2 must drive `/saas/session/activity` from actual authorized
meeting participation (including a long speaking/listening interval without mouse
input), recover/rejoin after reauthentication, and visibly handle absolute expiry.
No media token/WS fallback exists in M1. LiveKit revocation remains M2's live gate.

Owners assign/revoke roles; owner/admin rename, invite and revoke outstanding
invitations. All members may prepare private meetings. Only the organizer grants
meeting access to current members; workspace ownership does not imply private-meeting
access. Revocation removes the member's grants; re-invitation does not restore them.
Revoking an organizer leaves its private meeting inaccessible to them; no hidden
administrator takeover is provided. Explicit audited administration/ownership
transfer needs a reviewed policy before enabling that operation.

Invitations are member-only, verified-address-bound, seven-day and single-use.
Only hashes are stored. Links use fragments to avoid access-log/referrer leakage;
sharing is manual, with no email-provider write. Lists return at most 100 recent
meetings/invitations/audit entries; pagination is not implemented in this increment.
Workspace audit records actor/action/target/context, never invitation secrets or
profile content. Retention/deletion and audit export remain M5 work. Expired session
and attempt rows require routine maintenance; SID revocation markers are retained pending a reviewed deletion policy. Backups contain credential hashes and must be access controlled.

## Verification

```sh
# backend/ (both application and test DSNs must name disposable databases)
uv run --no-sync ruff check .
uv run --no-sync mypy
uv run --no-sync pytest tests/unit tests/integration tests/realtime -q -rs
# frontend/
npm run lint
npm run typecheck
npm test
npm run build
npm run test:e2e:saas
```

The SaaS browser configuration owns local backend/frontend processes and seeds
random server sessions **directly in the test DB**, not through a production bypass
route. Its fixture command refuses non-CI/non-`*_test` databases. It does not prove
Auth0 registration/recovery; signed mock-provider tests exercise that adapter's
validation separately. Keep database-mutating backend and browser tests sequential.
The PG migration test applies real revisions in a rollback-only schema and compares
models plus legacy values; it does not substitute for a sanitized operational
snapshot rehearsal, migration lock timing, or PostgreSQL 16 CI execution.

Migration rollback must retain the additive tables/columns and mode-aware access
checks. Do not serve old unfiltered prototype code over enterprise records as an
operational rollback. No real migration, downgrade or rollback was authorized or run.
