# M1 — enterprise SaaS foundation

Adds Auth0 hosted authentication integration with opaque PostgreSQL sessions,
application-owned accounts/workspaces, memberships, revocable invitations, private
meeting permissions, persistent account/meeting UI and additive legacy-safe
migrations. Logout/callback generation fencing, persistent organizer revocation,
explicit audited restoration and account-before-session locking address the
independent review findings.

The independent Reviewer approved implementation
`ebef4684f982f063c737deaf76cf8b65e71d32c7`; no unresolved M1 defects remain.
Subsequent commits document the human merge exception and prepare CI without
changing application or legacy ASR behavior; the generic reviewer prompt is a
separate documentation commit.

Local merge-preparation evidence: **538 backend tests passed, 1 explicit XFAIL**,
10 exception-policy cases passed, 115 frontend unit tests passed, lint/types/build,
real migration/schema checks, five offline security tests and actionlint passed.
Prior M1 browser evidence: 29 journeys passed. Both GitHub Actions jobs are
configured for PostgreSQL 16; **hosted execution and required-check results are
still outstanding**.

The human-approved exception covers only the independently verified M0
silent-participant ASR assertion. Its unchanged test executes under strict XFAIL;
other failures and unexpected passes fail CI. The exception is visible in console,
JUnit and the workflow summary. [M2-ASR-001](../follow-ups/M2-ASR-001.md) tracks its
resolution and exception removal during the audio lifecycle redesign.

Merge approval does not establish production readiness. Real Auth0
registration/recovery/revocation-event validation, approved provider region/cost,
and operational migration/backup/restore/rollback rehearsals remain deployment gates.
See [quality gates](../QUALITY_GATES.md) and [verification report](M1_DESKTOP_BUILD_REPORT.md).
