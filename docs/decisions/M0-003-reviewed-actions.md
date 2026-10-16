# M0-003: Versioned evidence and explicit approved Linear commands

Status: Proposed, 2026-10-15. IDs: ASR-03, AI-01..02, INT-01..03.

Raw final transcript is immutable; edits create revisions. Extraction references
an immutable snapshot and produces proposals only. Approval binds content,
evidence revision and destination; a transactional outbox carries the explicit
ticket request. Linear is the first and only proposed ticket connector.

This preserves provenance and hides OAuth/reconciliation behind three meaningful
operations (create, reconcile, fetch status). It adds version/command records but
avoids autonomous model writes and a speculative workflow framework. Changes to
approved content invalidate approval. Ambiguous writes stop for reconciliation;
local deduplication is not a claim of exactly-once provider behavior.

Review gate: approve the user action semantics; prove provider behavior in M4
sandbox tests before enabling writes. See [design](../M0_DESIGN.md).
