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

Final gate must be **APPROVE**, **CHANGES REQUIRED**, or **BLOCKED**, with reasons. Do not approve if any relevant P0/P1 remains, required tests fail, or key acceptance behavior is unverified. **Do not modify files.**
