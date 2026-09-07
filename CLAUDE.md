# Mosaïque — working agreement

Realtime meeting intelligence, French-first, for French SMBs. A host creates a
meeting, participants join from their own browsers, each microphone is streamed
separately, French speech is transcribed live with speaker attribution, and the
finalized transcript produces a summary, decisions, and action items.

Read `PROJECT_STATE.md` before doing anything. It is the only document that
describes what actually exists.

---

## Where truth lives

| Document | Authority |
|---|---|
| `docs/mosaique-prototype-technical-spec.md` | **Normative.** Contracts, schemas, thresholds, failure matrix. |
| `docs/mosaique-implementation-blueprint.md` | Reconciles contradictions between source documents; records decisions the spec left open. Wins only where sources conflict. |
| `docs/IMPLEMENTATION_PLAN.md` | What to build next. Vertical slices, each with an exit gate. |
| `PROJECT_STATE.md` | **Reality.** What exists, what is verified, what is a guess. |
| `docs/mosaique-future-media-plane-options.md` | **NON-NORMATIVE.** Future options. Governs nothing. Do not let it change prototype scope. |

When they disagree: reality beats intent, spec beats blueprint, blueprint beats
the rest.

---

## Non-negotiables

**Use `uv`, never `pip`.** Including in Dockerfiles.

**"Done" requires named test evidence.** `PROJECT_STATE.md` distinguishes
`IMPLEMENTED` (code merged, nothing proves it) from `VERIFIED` (a named test
passes, or a number was measured and written down). A passing demo is not
evidence. Never mark something `VERIFIED` without naming the test.

**Stay inside the slice.** Each slice in the plan lists what is deliberately
outside it. Building ahead is how the prototype turns into a platform project.
If something outside the slice looks necessary, say so and stop — do not
quietly widen scope.

**The seams are enforced by tests, not by convention.**
`backend/tests/unit/test_architecture.py` parses the source and fails the build
if anything downstream of the ingress imports FastAPI, Starlette, or
websockets, or if anything outside `speech/adapters/kyutai/` imports a model
library. If a change needs those imports to move, the design is wrong, not the
test.

**Two seams matter most:**
- `MeetingIngress` (blueprint D-04) — the runtime must not know where audio came from.
- `StreamingRecognizer` (spec §9.1) — `FakeRecognizer` and Kyutai are interchangeable.

**Timeline rule (ADR-11 / blueprint D-02).** Meeting time is derived from frame
counts with silence padding, never from client clocks. Silence detection is
judged in stream time, never wall time — audio arrives faster than real time in
every replay, and comparing the two fabricates segment breaks. This bug has
already been found once; do not reintroduce it.

**Only final segments are persisted.** Interim text lives in memory and is
disposable. Process memory is never the authoritative record.

**Values marked `[measure]` are guesses.** Do not tune them against the fake
recognizer. They are tuned in Slice 4 against real French audio.

---

## Commands

```bash
# backend (from backend/)
uv venv && uv pip install -e ".[dev]"
uv run alembic upgrade head
uv run python -m mosaique.app.seed            # prints a host token
uv run uvicorn mosaique.app.main:create_app --factory --reload --port 8000
uv run pytest -q                              # 117
uv run pytest -q -m "not integration"         # 85, no database needed
uv run ruff check . && uv run ruff format .
uv run mypy                                   # strict
uv run python tools/export_openapi.py ../frontend/openapi.json

# replay harness (from backend/, against a running server)
uv run python -m tools.replay run tools/replay/scenarios/two-participants.json \
  --host-token "$(uv run python -m mosaique.app.seed | tail -1)" --speed 10

# frontend (from frontend/)
npm install && npm run dev
npm run generate:api                          # regenerate typed client
npm run typecheck && npm test && npm run build
npm run test:e2e                              # Playwright, needs a running backend
                                              # MOSAIQUE_CHROMIUM_PATH overrides the browser
```

Regenerate `frontend/openapi.json` whenever an API route or schema changes: a
stale document means the generated client silently disagrees with the server.
This was meant to be enforced by a CI drift job, but **there is no CI in this
repository** — no `.github/` directory exists (L-18) — so the check is yours to
run before you push.

---

## Finishing a slice

1. The exit gate in `docs/IMPLEMENTATION_PLAN.md` is green.
2. `uv run pytest -q`, `ruff`, `mypy`, `npm test`, `npm run build` all pass.
3. `PROJECT_STATE.md` is updated: statuses moved, evidence named, new
   assumptions added to §7, measured numbers written into §8, limitations
   recorded in §10, and a changelog row appended.
4. Anything you could not verify is stated as unverified. Do not round up.

A slice is not finished until step 3 is done.

---

## Current state (2026-09-06)

Slices 0 and 1 are VERIFIED, browser flow included. Slice 2 is VERIFIED in
software: `tools/replay` v1, the multi-participant runtime, and the participant
panel. 137 tests: 85 backend unit, 32 backend integration against real
PostgreSQL, 18 frontend unit, 2 Playwright specs. Everything in the speech path
is a fake — no real audio has ever been transcribed by this system.

Two items on the Slice 2 gate are **not** done and are not claimed: the
cross-network run between two physical machines (A-8), and Spike A. Both need
hardware, not code. See `PROJECT_STATE.md` §9.

Next: **the two field checks above, then Slice 3 — failure behavior.**