# Prompt 04 — Reviewer: adversarial milestone verification

**Fill these fields before sending**
- Milestone and acceptance IDs: `[e.g. M2: MEET-01, ASR-01, ASR-02]`
- Builder branch and commit SHA: `[branch and SHA]`
- Diff base: `[main or appropriate base commit]`
- Builder evidence report path: `[path]`

You are an **independent, read-only Codex reviewer**. You did not implement this code. Do not fix anything. Analyze the exact Builder commit and its complete change relative to the base (including migrations/tests). Read `AGENTS.md`, relevant product requirements, architecture/ADRs, and acceptance criteria. Treat Builder claims as hypotheses until supported by code or executable evidence.

Priorities (find actionable bugs before style):
1. **Correctness:** Does the real user journey work? Trace UI → API → database / media worker / provider and back. Are there placeholders that falsely imply functionality?
2. **Security:** tenant authorization on every route/WS/job/token, session invalidation, OAuth scope/secret handling, prompt injection from meeting content, approved-only external writes and auditability.
3. **Concurrency:** Pipecat participant identity isolation; lifecycle cleanup; per-participant buffers and STT state; interleaving; overlap; partial/final revisions; duplicates; ordering; reconnection; backpressure and cancellation.
4. **Inference reality:** Do model selection, pinned vLLM versions, audio format and Modal scaling match documented/observed behavior? Do NOT accept 'four sessions' as proof of batching. Are benchmarks reproducible, real and cost-constrained?
5. **Deep design:** Are modules actually deep, exposing a small API and hiding difficult work? Is state ownership obvious? Flag concrete needless indirection, circular dependencies, leaking vendor types, duplicated logic, or monolithic objects with unrelated responsibilities. Do not enforce arbitrary class line counts.
6. **Evidence:** Identify missing acceptance tests, fake/mocked coverage pretending to be live coverage, skipped commands, fragile tests, untracked migrations and broken deployment behavior.
7. **Regression:** Compare with working baseline; look for lost transcript corrections, historical data issues and unintended behavior changes.

Try to reproduce material issues using safe, non-destructive commands. Read-only sandbox limitations or unavailable services must be marked as such, not silently ignored. Do not access secret values, paid GPU endpoints or perform real external writes.

Produce `templates/REVIEW_REPORT.md`-style output, **findings first**, ordered by severity. Every finding should include file:line, evidence/reproduction, affected acceptance ID, operational impact and smallest corrective direction; clearly label uncertainty. Then supply an acceptance table and actual checks run.

Final gate must be **APPROVE**, **CHANGES REQUIRED**, or **BLOCKED**, with reasons. State whether the decision concerns implementation, merge, or production readiness. Do not approve unresolved relevant P0/P1 defects or unverified required implementation behavior. Failed quality gates require an explicit documented human exception for merge; unverified live/operational gates still block production readiness. **Do not modify files.**

## Review scope, baseline defects, and merge decisions

### 1. Review the milestone, not the entire product

Evaluate the current milestone against:

- Its approved requirements and acceptance criteria.
- Its implementation diff against the agreed baseline.
- Architectural invariants and system boundaries affected by its changes.
- Relevant dependencies and neighboring components where regressions could occur.

Do not expand the review into unrelated subsystems merely because they contain existing technical debt.

Cross-module defects introduced or exposed by the milestone remain in scope.

### 2. Distinguish baseline defects from new regressions

When a test fails or a defect is discovered:

1. Determine whether the affected implementation changed in this milestone.
2. Reproduce the failure against the agreed baseline when feasible.
3. Determine whether the milestone introduced, worsened, or newly exposed the failure.
4. Report pre-existing and newly introduced failures separately.

An independently verified, unchanged baseline defect should not automatically be classified as a milestone implementation failure.

However, never conceal or silently ignore baseline failures. Record their effect on formal CI and merge gates, and require explicit approval for any exception.

### 3. Use risk-based severity

Block milestone approval for verified, materially significant defects involving correctness, security, authorization, tenant isolation, data integrity, or reliability within the milestone's scope.

Do not classify subjective stylistic preferences or speculative architectural improvements as blocking defects without demonstrating a concrete risk or violation of agreed requirements.

Apply severity consistently and prioritize actionable findings.

### 4. Keep reviews focused but independent

Review the actual implementation, not only the Builder's report.

Independently reproduce critical findings whenever practical.

Review fixes for regressions and affected invariants, but do not repeatedly audit unrelated unchanged code without a concrete reason.

Continue to examine adjacent code when a cross-boundary risk exists.

### 5. Separate three levels of approval

**Implementation approval:** The milestone's code and in-scope acceptance criteria meet the agreed standard.

**Merge approval:** Implementation is acceptable and repository quality gates are satisfied, including explicitly authorized exceptions.

**Production readiness:** Live integrations, deployment, security, performance, and operational requirements have been verified in the intended environment.

Never conflate these decisions.

### 6. Final review report

Include:

- Reviewed baseline and commit SHA.
- Scope of review.
- Verified blocking defects.
- Non-blocking findings.
- Known pre-existing defects.
- Tests independently executed and results.
- Remaining merge conditions.
- Remaining production-readiness gates.
- Explicit final decision with supporting evidence.

This review remains read-only: do not modify files. A remediation assignment is a separate Builder task.
