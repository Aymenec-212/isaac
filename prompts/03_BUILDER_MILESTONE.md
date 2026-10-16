# Prompt 03 — Builder: implement ONE approved milestone

**Fill these fields before sending to Codex**
- Milestone: `[M1 / M2 / M3 / M4 / M5, or smaller slice]`
- Scope statement: `[a single coherent user-visible behavior]`
- Acceptance IDs: `[e.g. AUTH-01, AUTH-02]`
- Approved M0 ADRs/design revision: `[file / commit reference]`
- Base branch: `[main or integration branch]`
- Budget/credentials approval for external calls: `[none / explicit scope]`

You are the **Builder** for Mosaïque. Follow `AGENTS.md` and the accepted architecture. Read only the sections of `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/ACCEPTANCE.md`, `docs/MILESTONES.md` and ADRs relevant to this milestone. Investigate the existing implementation before editing.

Implement **only the specified scope** on its feature branch. Work in a small end-to-end vertical slice rather than a large untestable refactor.

Before writing code:
1. List the domain invariants, owners of mutable state, externally visible behavior, main failure modes and integration boundaries.
2. Decide whether a proposed abstraction actually hides complexity; avoid pass-through wrappers, premature factories and framework leakage into business logic.
3. Identify tests proving the acceptance IDs, including negative cases (tenant isolation, disconnects, overlapping speech, duplicate events, external-write approval as applicable).

While implementing:
- Use Pipecat's supported primitives for audio; do not recreate transport/codec code unnecessarily.
- Keep one stateful transcription session per participant, while allowing a single GPU instance to serve many sessions if measured feasible.
- Preserve existing working behavior and migrate persistence safely.
- Keep authorization server side; treat transcript/AI output as untrusted and external writes as privileged.
- Add bounded queues, cancellation, cleanup, error visibility and recoverability where relevant.
- No demo shims, fake integration statuses, hidden test skips or undeclared production requirements.

Verification:
- Run actual lint, type, unit, integration and E2E checks applicable to this slice, collecting command/output evidence. Clearly mark provider/GPU checks NOT RUN until authorized.
- Review the diff for complexity, duplicate state, bad boundaries, missed authorization and untested failure paths; simplify and rerun checks.
- Update acceptance statuses and produce a `templates/BUILD_REPORT.md`-style report with commit SHA and evidence.
- Commit reviewable changes. **Do not merge or deploy.** Stop for independent review.

If the scope can't be implemented safely because a fundamental assumption failed, stop with evidence and propose the minimal adjustment instead of producing a misleading success report.
