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
already been found twice — see Known traps; do not reintroduce it.

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
uv run pytest -q                              # 152, 1 deselected
uv run pytest -q -m "not integration"         # 104, no database needed
uv run pytest -q -m slow                      # the accelerated hour, ~70 s
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

## Current state (2026-09-07)

**Slices 0 through 3 are VERIFIED and merged to `main`** (PR #1, PR #2). 181
tests: 104 backend unit, 48 backend integration and realtime against real
PostgreSQL, 27 frontend unit, 2 Playwright specs — plus a 60-minute accelerated
run behind `-m slow` that passes at 54.8x realised with no memory growth.

The product spine works end to end on fakes, two participants merge into one
attributed transcript in both browsers, and every row of the tech spec §14.1
failure matrix that does not need a real model has a named passing test.
**Everything in the speech path is still a fake — no real audio has ever been
transcribed by this system.**

Three things are open and none of them is code: the cross-network run (A-8),
Spike A, and the GPU half of A-9. All need hardware.

Next: **Slice 4 — real Kyutai**, blocked on Q2, Spike B and Spike C. It is also
the slice that can invalidate earlier work, because every `[measure]` value has
so far been tuned against a recognizer that emits a fixed script at a fixed
delay. Start from `PROJECT_STATE.md` §12.

---

## Known traps

Four mistakes this codebase has actually made. Each cost real debugging time
and each is easy to repeat.

**Stream time is not wall time.** Silence and segment boundaries are judged in
stream time derived from frame counts (ADR-11), never against a clock. Broken
twice: once in Slice 1, once in Slice 2 where the frame pump still ticked the
segmenter with audio *pushed* rather than audio *transcribed*.

**Per-participant tasks share runtime state.** Every pump runs concurrently and
touches the same runtime objects, so anything mutated across an `await` needs a
lock. The persistence buffer did not have one and silently dropped a segment
that had already been broadcast — no error, no log, invisible to the fast suite.

**Globs in `.gitignore` are not anchored.** A bare `audio/` also matched the
source package `backend/src/mosaique/speech/audio/`, so `store.py` was never
committed and a clean checkout could not import the app. Anchor runtime-data
rules with a leading slash, and check `git check-ignore -v` when a file vanishes.

**Never hold a socket open while doing slow work.** The server hangs up after
30 s of silence (§7.4), and it is right to. The harness generated an hour of
synthetic audio *after* connecting and looked exactly like a dead client;
generate first, connect second, and yield inside any tight send loop.

