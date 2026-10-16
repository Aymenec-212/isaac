# Mosaïque — Verification and Independent Review Protocol

## Four distinct forms of evidence
1. **Behavior:** executable unit/API/integration/browser E2E, with negative and simultaneous-speech tests.
2. **Structure:** dependency/import-boundary checks, type checking, lint and meaningful module ownership.
3. **Operations:** real LiveKit/Modal/provider sandbox tests, logs, failure injection, performance and cost measurements when approved.
4. **Design judgment:** independent review for deep modules, small interfaces, coherent error ownership, unnecessary indirection and framework coupling.

## Verification toolchain (discover exact commands during M0)
- Python: pytest, Ruff, Pyright or mypy, real PostgreSQL integration tests.
- Frontend: strict TypeScript, ESLint, its existing test runner, Playwright.
- CI: GitHub Actions running actual commands and required checks on PRs.
- Create `scripts/verify` only after discovering repo commands; don't add a green placeholder that omits checks.
- Keep GPU and external-provider tests separately labeled and never report simulated provider tests as real.
- Be careful with flaky live calls; use deterministic fixtures for ordinary CI and nightly/on-demand real tests when cost is approved.

## Verification report, per commit
- Milestone, base branch, tested commit SHA, date and environment.
- Acceptance IDs and status, with tests proving each.
- Commands executed, pass/fail/blocked/not-run and artifacts.
- Security and architectural risks, added and removed complexity.
- Actual (not estimated) GPU/live integration results when used.
- Changed files and migration implications.
- Reviewer findings, how resolved, outstanding findings and explicit blockers.

## Architecture fitness rules
- Domain packages do not import Pipecat, LiveKit, vLLM, Modal, HTTP routers or provider-specific clients.
- No direct provider calls in browser-facing handlers for approved business integrations.
- No cross-tenant read/write without explicit authorization check.
- Participant media/STT session state is never shared across participants.
- Verify important rules automatically if import structure makes that possible; otherwise reviewer must check. Avoid arbitrary class-length metrics.

## Review severity
- P0: security boundary failure, data disclosure, irreversible unintended action, destructive migration.
- P1: correct workflows broken, transcript mixups/loss, unrecoverable operation, invalid external effects, important test gaps.
- P2: reasonable quality/race/maintainability risk with concrete evidence.
- P3: nonblocking improvement/suggestion. Avoid cosmetic review noise.

## Gate
Merging requires no unresolved P0/P1 findings and passing locally executable required checks. External integrations marked `NOT RUN`/`BLOCKED` are release blockers when their behavior is part of the milestone's acceptance claim. Human approval always required.

## M1-only baseline exception — M2-ASR-001

On 16 October 2026 the human owner confirmed independent implementation approval
of M1 commit `ebef4684f982f063c737deaf76cf8b65e71d32c7`, with no unresolved M1
defects, and explicitly authorized a **narrow merge exception** for this exact test:

`backend/tests/realtime/test_idle_and_pause.py::test_a_silent_participant_does_not_claim_the_recognizer_stream`

The independent Reviewer verified it failing on the M0 baseline. Ordinary M1
verification at `ebef468` reported **528 passed, 1 failed, 1 skipped, 1 deselected**;
the sole failure is the assertion that the silent participant is absent from
`runtime._sessions` (the identical assertion appears at two points in that test).
Legacy prototype join eagerly creates the stream/audio state and opens the
recognizer before the first frame. M1 enterprise identity/workspace changes do not
modify that lifecycle or expose the prototype media surface in enterprise mode.
It is a retained baseline resource-allocation defect, not an unresolved M1 defect.
Root cause, owner, acceptance and removal conditions are tracked in
[M2-ASR-001](follow-ups/M2-ASR-001.md); it must be resolved during M2 lifecycle work.

The human authorization overrides only this baseline failure as an M1 merge gate.
It does not waive another test, security defect, live acceptance gate or M2 exit
criterion. Independent approval applies to the reviewed implementation; the
subsequent CI/documentation preparation remains visible in its own commit.

### Temporary CI mechanics

GitHub Actions executes the full existing selected backend suite with the explicit
opt-in `-p tools.m1_merge_exception` and `-rxXs --junitxml=...`. The legacy test is
unchanged and its body executes. The plugin uses pytest's strict expected-failure
support, matches exactly one collected node and accepts only `AssertionError`
originating from the existing `silent[...] not in runtime._sessions` assertion in
that function/file. A changed assertion/error, setup or teardown failure, missing
or duplicated node, strict XPASS, or any additional failing test still fails CI.
There is no broad `continue-on-error`, deselection, test-body skip or exit-code
suppression. Ten subprocess policy cases verify these limits. The locked pytest
version supports the exception predicate; use the frozen dependency workflow.

Console output and the backend JUnit artifact visibly report **XFAIL** with this
human-approved reason and M2-ASR-001. GitHub's job summary explains the active
exception. JUnit represents an expected failure as `skipped type="pytest.xfail"`;
this is an executed expected failure, not a skipped body. Ordinary local pytest
without the plugin continues to report the original failure. Do not broaden this
exception to make CI pass; new failures must be fixed or independently reviewed.
Retire the exception when the regression passes: strict XPASS forces attention.

### Merge approval versus production readiness

This explicit exception permits the M1 baseline failure to be accounted for at
merge. Actual hosted required checks must still pass; implementation approval and
local verification do not prove hosted CI. Keep `Verify / backend` and
`Verify / browser` required in repository branch protection (a hosted setting to
verify, not something this document configures). No merge is performed by Builder.

Real Auth0 hosted registration/login/recovery and revocation-event delivery,
approved provisioning/region/cost, PG16 hosted execution, and sanitized operational
migration/backup/restore/rollback and old-process-drain rehearsals remain unverified.
These are deployment/pilot gates, unaffected by the merge exception. The baseline
ASR limitation must remain visible until M2-ASR-001 is closed. No production-readiness
or M2-completion claim follows from a green M1 job with one expected failure.
