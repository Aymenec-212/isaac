# Builder fix report — M0 independent review

Status: corrected proposal ready for **re-review**, not architecture approval.
No application implementation, migration, merge, deployment or cloud spending.

## Comparison bases and scope

- Branch: `codex/m0-architecture`.
- Requested review base: main `6e9e85bd3806cf7f5c0205ece97e285f8d62da9e`.
- Immediate original Builder starting point: `7412d8d9b6cc66f928d4cf01a57d2a65b20127fb`.
- Reviewed proposal / this fix's parent: `d8204d4fa0d16a79968023fc542de275e3811746`.
- Fix SHA: the commit containing this report, provided in the final handoff;
  resolve with `git log -1 --format=%H -- docs/reports/M0_FIX_REPORT.md`.
- Acceptance scope: OPS-02 regression preservation; MEET-01/02, AUTH-04 and
  OPS-03 end lifecycle; ASR-03/04 and AI-01 quality gates. Supporting review
  observations map to AUTH-01..03 and INT-01..03.

All three findings are accepted. R1 was reproduced; R2/R3 are verified omissions
in the proposal, not runtime defects reproduced against an implementation. The
earlier report's baseline description was incomplete: the fixture loss happened
inside the reviewed branch. It must be fixed in M0, not assigned to M1.

## Finding disposition

| Finding | Status / root-cause correction | Modified files | Verification and limitations |
|---|---|---|---|
| P1 M0-R1 | Fixed branch regression: restore the three required data files byte-for-byte from main; no altered/skipped assertions. Document both bases and provenance | `docs/mosaique-b1-main/{b1-report.json,b1-tokens.jsonl,PROVENANCE.md}`, `docs/slice4-last-test-report.json`, discovery/migration and reports | Reviewer command: 33 pass/13 fail before, 46 pass after. Full unit suite: 348 pass. All restored Git blobs match main. Historical developer speech reports, no recordings/credentials restored |
| P1 M0-R2 | Fixed specification: durable end owner/operation, atomic admission closure, bounded transcript drain concurrent with media disconnection, all-issued-identity revocation, deletion/rejoin check, durable retry/recovery, truthful pending UI | `M0_DESIGN.md`, `M0_MIGRATION.md`, `M0_THREATS.md`, acceptance update | Manual contract/transition review and explicit M2 negative/crash test matrix. Cloud APIs inspected read-only; runtime tests NOT RUN. DeleteRoom is not assumed to ban old tokens; unresolved Cloud semantics block closure |
| P2 M0-R3 | Fixed gate omission: per-language accuracy, hard evidence-window limit, timing-error bounds after lifecycle changes, and durable-final latency must have approved thresholds and qualification evidence | `M0_DISCOVERY.md`, `M0_DESIGN.md`, `M0_MIGRATION.md`, `M0_THREATS.md`, acceptance update | Threshold record/measurement/failure disposition specified. Numbers remain unset and therefore block M2 closure until explicit product decision. No GPU measurements or invented quality claim |

Also addressed non-finding review observations: commit-order-safe cursor replay
tests; crash-after-provider-success reconciliation; profile/workspace settings,
explicit destination-owner mapping and tracked status tests. Removed the two
trailing-whitespace lines in `templates/BUILD_REPORT.md` reported by the Reviewer.
These are narrow planning/tooling-document corrections, not application changes.

## Executed verification

Local macOS, existing Python 3.12 backend virtualenv. No installs. Full suite uses
the previously authorized localhost-socket access; no DB fixture was invoked.

```sh
# backend; exact Reviewer reproduction, before and after fixture restore
.venv/bin/python -B -m pytest -p no:cacheprovider --capture=sys \
  tests/unit/test_measured_timing.py tests/unit/test_prompt_budget.py \
  tests/unit/test_authorization.py tests/unit/test_state_machine.py \
  tests/unit/test_output_schema.py -q --tb=line
# backend; after restoration
.venv/bin/pytest tests/unit -q -rs --tb=short
```

| Check | Observed result |
|---|---|
| Targeted pre-fix reproduction | FAIL: 33 passed, 13 failed, FileNotFoundError for the two report paths |
| Targeted post-fix | PASS: 46 passed |
| Full unit suite post-fix | PASS: 348 passed, zero failures/skips |
| Fixture integrity | PASS: bytes and Git blob hashes equal main for all three files; JSON/JSONL parsed |
| Branch whitespace | PASS: `git diff --check main` after template correction; staged comparison checked before commit |
| Application boundary | `git diff main -- backend frontend` and corresponding staged comparison empty; application source, tests and locks unchanged |
| Documentation links/scope | Local relative-link targets checked; changed proposal manually inspected against all review findings; only selected docs/fixtures/template staged |

Existing regression tests already fail before and pass after restoration, so no
duplicate fixture-presence test was added. R2/R3 receive test plans only because
this is M0. Frontend, mypy and Ruff were not rerun for these docs/fixture changes;
earlier Builder results are inherited, and the Reviewer had a different frontend
dependency environment. Known MLX type and frontend ESLint setup gaps remain;
passing units does not make OPS-02 verified. Database/realtime integration, browser
E2E, LiveKit, Modal/GPU and provider writes remain **NOT RUN**.

## Preservation and remaining review gate

Restored data provenance is documented in [PROVENANCE.md](../mosaique-b1-main/PROVENANCE.md).
Original report remains as historical evidence with a correction/link to this report.
Unrelated pre-existing unstaged deletions of CLAUDE.md, CODEX_HANDOFF.md,
PROJECT_STATE.md, README.md and four infra/azure files remain untouched/excluded.
Other historical documentation removed in 7412d8d is not broadly restored; the
three files fix the observed unchanged-test consumers without reviving superseded
architecture specifications. Compare against both main and d8204d4 on re-review.

No finding is contested. All enterprise acceptance statuses remain unverified.
Exact runtime pins, isolation/cleanup tests, approved 1/2/4 GPU measurements,
migration/restore rehearsal and Linear ambiguity reconciliation remain required.
Provider suitability, privacy/residency and paid-test authorization remain human
decisions. Reviewer should recheck restored blob identity, complete end/rejoin
semantics and mandatory quality-gate failure handling. Stop for independent
re-review and explicit human approval; do not begin M1.
