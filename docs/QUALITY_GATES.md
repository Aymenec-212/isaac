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
