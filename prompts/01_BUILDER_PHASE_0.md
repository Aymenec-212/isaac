# Prompt 01 — Builder: M0 architecture discovery only

You are the **Builder** for Mosaïque. This repository is transitioning from a transcription prototype to a secure, multi-tenant enterprise meeting intelligence product.

First inspect the repository and read `AGENTS.md`, `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/ACCEPTANCE.md`, `docs/MILESTONES.md`, `docs/QUALITY_GATES.md` and `docs/MODAL_REFERENCE.md` (the reference may still be unverified). These files define the objective, not a mandate to implement hypothetical abstractions.

**DO M0 ONLY. Do not begin the rewrite.**

1. Inventory the existing app with file references: browser frontend; auth (if any); FastAPI handlers/WS protocol; PostgreSQL/data migrations; ASR runtime; summary/action handling; infra/deployment; tests; known regressions.
2. Produce a reuse/retire/replace matrix for actual modules; identify existing functionality we must preserve. Include an incremental database/migration strategy and avoidance of destructive rewrites.
3. Study relevant *current* Pipecat LiveKit transport/frame/lifecycle code, LiveKit Cloud APIs, vLLM Voxtral Realtime streaming protocol and Modal GPU serving. Pin or recommend compatible versions based on evidence. Do not assume efficient cross-session GPU batching: articulate a benchmarking experiment on L4 with 1, 2 and 4 live STT sessions.
4. Use `docs/MODAL_REFERENCE.md` and, if a safely authorized path is accessible, inspect code from the old Voxtral project **read-only**. Never copy secrets or assume its protocol matches Voxtral Realtime.
5. Propose the minimal coherent modular-monolith architecture, domain invariants, authenticated participant-to-LiveKit-to-Pipecat identity mapping, session isolation, transcript event/revision/timestamp semantics, auth strategy, tenancy, human approval and one integration boundary.
6. Produce a threat model of trust boundaries, tenant leaks, token lifetimes, recording/transcription privacy, untrusted AI output, external integration writes and service failure.
7. Update proposal docs and write small ADRs for major decisions only. Provide an ordered milestone implementation plan tied to acceptance IDs, measured exit criteria and tests. Identify unresolved research questions separately.
8. Propose realistic CI/verification commands after identifying actual project tooling; never claim a test passes unless executed.

**Phase gate:** Limit changes to architecture/planning/docs and necessary non-destructive investigation. Do not modify application source or deploy cloud services. Present the proposed design, significant trade-offs, implementation sequencing, tests actually run, and review questions. Then STOP for an independent Reviewer and explicit human approval.

Deliver a M0 report using `templates/BUILD_REPORT.md` (fill with observed details). Keep code and the working baseline intact.
