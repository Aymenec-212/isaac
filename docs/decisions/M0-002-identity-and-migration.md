# M0-002: Proven identity provider, application-owned tenancy, additive migration

Status: Proposed, 2026-10-15. IDs: AUTH-01..04, HIST-01, OPS-01.

Recommend Auth0 OIDC with server cookie sessions. Accounts are global;
organization memberships and meeting permissions are local and rechecked.
Expand the existing schema with explicit legacy identity mappings; preserve IDs,
raw transcripts and corrections. Never merge accounts by email or convert old
participant tokens into enterprise authority. See [migration](../M0_MIGRATION.md).

This avoids custom password/recovery cryptography and allows multiple memberships,
at the cost of an external identity dependency and a reviewed migration/claim flow.
Provider pricing/residency approval remains open. Reject a database reset and
authorization solely from token role/org claims. RLS may be added as defense in
depth after pool/worker context tests; it does not replace application authorization.

Review gate: provider/policy approval and a disposable migration rehearsal before
any real data changes. No provider account or database is provisioned by this ADR.
