# Mosaïque — Phased Delivery and Human Gates

M0's proposed ordered slices, measured exit targets and actual-tooling CI plan are
in [M0_MIGRATION.md](M0_MIGRATION.md). This supplements the milestone boundaries
below; it does not authorize implementation. [M0 report](reports/M0_BUILD_REPORT.md)
records the baseline and open review gate.

## M0 — Architecture discovery (documentation only)
- Map current code, behavior, tests and unknowns.
- Inspect sanitized notes from prior Voxtral deployment.
- Verify upstream Pipecat/vLLM/Modal interfaces against pinned/current sources.
- Propose domain modules, trust boundaries, data migrations, deployment topology and ADRs.
- Identify what to keep, replace and delete; rank risks; update acceptance matrix and next-milestone plan.
- **STOP** for independent reviewer and human architecture approval before code rewrite.

## M1 — SaaS foundation
Account identity, multi-organization membership, invitations, authorization, core meeting schema and real account/workspace UI. Required tests for IDOR, revoked access, org switching and persistence. Operational auth/tenant security is part of M1, not future polish.

## M2 — LiveKit + Pipecat + concurrent Voxtral
Authenticated room tokens; two-user real meeting and browser controls; isolated per-participant audio pipelines; shared inference engine; live attributed transcript. Record overlaps, lifecycle/failure handling and actual GPU benchmarks under approved credentials/budget. Do not claim M2 complete without honest integration evidence.

## M3 — Durable meeting intelligence
Final transcript lifecycle, meeting history, corrections/search, async summary, evidence-backed structured decisions/actions, review and approval UX, recovery/idempotent jobs.

## M4 — One real external workflow
Pick one destination (Linear *or* Jira), org-scoped integration auth, human-approved action → ticket; persist external ID, retries/reconciliation, audit trail, status retrieval and cross-tenant security tests.

## M5 — Pilot-grade operational readiness
Threat-model review, privacy and retention, monitoring/alerts, backup/restore and migration rehearsal, cost and performance measurements, security review, operational runbooks. Describe gaps before offering actual pilots.

## For every milestone
- Builder implements one reviewable vertical slice and produces evidence.
- Reviewer independently inspects code, checks source requirements, reproduces feasible tests and returns prioritized findings.
- Builder fixes confirmed blocking issues, updates tests, and submits new commit.
- Reviewer rechecks new commit and changes to scope.
- Human approves merging. Do not automate merges or paid deployments.
