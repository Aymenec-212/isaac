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

**Three seams matter most:**
- `MeetingIngress` (blueprint D-04) — the runtime must not know where audio came from.
- `StreamingRecognizer` (spec §9.1) — `FakeRecognizer` and Kyutai are interchangeable.
- `KyutaiBackend` (ADR-13, `speech/adapters/kyutai/backend.py`) — the model is
  fixed; `mlx` and `moshi_server` are two ways of running it. See the runtime
  policy below.

**Timeline rule (ADR-11 / blueprint D-02).** Meeting time is derived from frame
counts with silence padding, never from client clocks. Silence detection is
judged in stream time, never wall time — audio arrives faster than real time in
every replay, and comparing the two fabricates segment breaks. This bug has
already been found twice — see Known traps; do not reintroduce it.

**Only final segments are persisted.** Interim text lives in memory and is
disposable. Process memory is never the authoritative record.

**Values marked `[measure]` are guesses.** Do not tune them against the fake
recognizer. They were tuned in Slice 4 against real French audio; the ones that
are now measured say so in `PROJECT_STATE.md` §8, and most still do not.

**Providers are configuration, not architecture — both of them.** The same rule
now covers two axes: `asr_runtime` (`fake` / `mlx` / `moshi_server`) and
`llm_provider` (`fake` / `openai`). Both default to `fake`, both fail fast on a
missing key or URL rather than silently downgrading, and both keep the vendor's
client out of the layer that uses it — `asr_runtime/` and `llm_runtime/` hold
the sockets, `test_architecture.py` holds the line. A silent fallback to a fake
is the failure both guard against: scripted French in a real transcript, or an
invented decision in a real summary, with only `asr_version` / `llm_model` to
show for it afterwards.

MLX in particular is what this project develops and measures against today, because it is what the available hardware
runs. It is not an infrastructure decision, and no layer above the adapter may
assume it. `moshi_server` is the deployment path and already exists behind the
same `KyutaiBackend` Protocol, unrun for want of a CUDA host. Swapping them must
stay a config change: if replacing the backend would touch the meeting,
transcript, or realtime layers, the seam has been broken and that is the bug.
Two consequences worth knowing before you trust a number: MLX carries no VAD
heads, so `EndOfTurnEvent` never fires there and §9.3's primary closing rule is
dead code on this runtime; and every figure in §8 measured on MLX describes
bf16-on-Apple-silicon, not production (A-16).

---

## Commands

```bash
# backend (from backend/)
uv venv && uv pip install -e ".[dev]"
uv run alembic upgrade head
uv run python -m mosaique.app.seed            # prints a host token
uv run uvicorn mosaique.app.main:create_app --factory --reload --port 8000
uv run pytest -q                              # 380, 1 deselected
uv run pytest -q -m "not integration"         # 305, no database needed
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

## Current state (2026-09-08)

**Slices 0 through 4 are VERIFIED and merged to `main`. Slice 5 is code
complete, its gate open.** 366 tests: 258 backend unit, 57 backend integration
and realtime against real PostgreSQL, 49 frontend unit, 2 Playwright specs —
plus a 60-minute accelerated run behind `-m slow` that passes at 54.8x realised
with no memory growth.

**Slice 5 works against the real provider** — confirmed by Aymen on 2026-09-08.
The OpenAI adapter, strict structured outputs, the FR-11 audio route and the
evidence-linked review page all function end to end. What is **not** measured:
the ten-meeting run, A-6's schema-rejection rate split by reason, and cost per
meeting (L-31). One good run is not a rate.

**The plan was re-sequenced on 2026-09-08 into three phases.** Read
`docs/IMPLEMENTATION_PLAN.md` v1.3 before picking up work:

- **Phase A — now.** Slice 6A: harden the complete single-user product on
  M1 + MLX. Health endpoints per dependency, transcript search, a long run
  against the real runtime, full-lifecycle tests, degraded-state UX.
- **Phase B.** Slice 6B: deploy `moshi-server` on a dedicated NVIDIA host and
  measure the production serving path. Blocked on hardware, not on code.
- **Phase C.** Slice 6C: four participants, with the original Slice 6 exit gate
  carried over unchanged.

**Slice 6 was split, not reduced.** Four participants, concurrent ASR, CUDA
validation and GPU benchmarking are all postponed and all still tracked. **L-26
— MLX serves one stream per process — is therefore no longer an immediate
blocker**: it is sufficient for Phase A and disqualifying for Phase C, and the
only thing that changed is which one is next.

**Real French audio has now been transcribed end to end, once.** 116.36 s
through the running app-server against real MLX Kyutai on Apple silicon,
2026-09-08: **1.43% WER**, p95 first-word latency **1 934 ms**, 30 segments all
persisted, `asr_version` written as `kyutai/stt-1b-en_fr@mlx-bf16` by the
app-server rather than hard-coded. Evidence: `docs/slice4-last-test-report.json`.

Read that as narrowly as it deserves. It is one speaker, one stream, one
prepared monologue, clean audio, on one machine — and **nothing re-runs it**:
the model path needs Apple silicon, this repository has no CI (L-18), and no
sandboxed session can execute it. Of the latency, 1 343 ms of 1 343 ms is the
model; the transport either side is noise.

The same run found a defect its WER could not see: **8 of 30 segments are a
sentence's final word alone in a 160-400 ms segment** (L-28). **Deferred by
decision, not oversight** — reassess at the end of Slice 5, and only if it has
shown real impact on meeting intelligence, evidence linking or transcript
correctness. `tests/unit/test_l28_orphaned_final_word.py` pins its shape
meanwhile; Slice 5 builds no special case around it. Do not reopen it
unprompted, and do not encode its suspected cause anywhere — that is still a
hypothesis.

Still hardware-blocked, now explicitly Phase B/C rather than open-ended: A-3 and
A-16 and `moshi_server` and `EndOfTurnEvent` (a CUDA host), the cross-network run
(A-8), Spike A, and the GPU half of A-9.

**Say where, not just whether.** `PROJECT_STATE.md` §0 now carries a
validation-environment vocabulary — ✅ M1 + MLX, ✅ fake, ⚠ implemented-not-
validated, ❌ needs NVIDIA, ❌ needs cross-network — because a number measured on
MLX does not describe CUDA (A-16). **Never mark the production GPU serving path
verified until it has actually served a meeting.**

Next: **Slice 6A**. Start from `PROJECT_STATE.md` §12.

---

## Known traps

Five mistakes this codebase has actually made. Each cost real debugging time
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

**A model's clock can run ahead of its own words.** On the first real fixture the
silence tick closed 8 of 30 segments where the audio has only a 160-560 ms gap,
orphaning each sentence's last word — and WER scored 1.43% straight through it.
The suspected cause is emission lag outrunning `transcribed_offset_ms`; that is
inferred, not observed (L-28). Judge segmentation by looking at boundaries, never
by a word-level score.

