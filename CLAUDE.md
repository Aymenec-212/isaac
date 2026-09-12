# Mosaïque — working agreement

> **Current amendment — 2026-09-12:** [Two-user voice / Azure ASR architecture](docs/two-user-cloud-architecture.md)
> records the maintainer's new priority and supersedes companion-only D-01/ADR-01,
> the WebRTC exclusion and older single-user-first sequencing where they conflict.
> Direct WebRTC/TURN carries voice; the existing PCM WebSocket and ASR seams remain.
> Work proceeds one slice, one documented PR, review/merge, then the next slice.
> R0 merged as PR #19. [R1 deployment configuration](docs/r1-azure-deployment.md) is ready
> for review; Azure GPU feasibility is blocked and no resources are deployed.
> Historical text below retains its evidence; use root PROJECT_STATE.md for next work.

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
uv run pytest -q                              # 398, 1 deselected
uv run pytest -q -m "not integration"         # 305, no database needed
uv run pytest -q -m slow                      # the accelerated hour, ~70 s
uv run ruff check . && uv run ruff format .
uv run mypy                                   # strict
uv run python tools/export_openapi.py ../frontend/openapi.json

# replay harness (from backend/, against a running server)
uv run python -m tools.replay run tools/replay/scenarios/two-participants.json \
  --host-token "$(uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')" --speed 10

# frontend (from frontend/)
npm install && npm run dev
npm run generate:api                          # regenerate typed client
npm run typecheck && npm test && npm run build   # 91 unit tests
npm run test:e2e                              # Playwright, 19 specs, needs a running backend
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

## Current state (2026-09-10)

*Read this section, then `PROJECT_STATE.md` §12. Between them you should be able
to start work without asking anyone a question.*

### Where the project is

**Slices 0–5 are VERIFIED and merged. Slice 6R is COMPLETE and validated on the
M1 (2026-09-10, PR #16). Slice 6A is five of six done — its last item, the
remaining §15 metrics, is the only thing left in Phase A.**

**516 tests**: 305 backend unit, 93 backend integration and realtime against real
PostgreSQL, 91 frontend unit, 19 Playwright browser specs. Plus a 60-minute
accelerated run behind `-m slow`. **All four suites were re-run by Aymen on his
M1 on 2026-09-10 and are green — backend `398 passed, 1 deselected`, frontend
`91 passed`, 19 browser specs, typecheck and build clean.** That number now
matches what this repository produces in CI-less sandboxes exactly, which is the
only cross-check there is (L-18). Migration `0002` applied cleanly against his
database, not just against a sandbox one.

The product works end to end for one participant on real hardware, **corrections
included**. Aymen ran a full manual meeting on **real MLX Kyutai + OpenAI
`gpt-4o-mini`** on 2026-09-10: MLX weights loaded, PostgreSQL healthy and OpenAI
configured on `/readyz`, live French transcript, grouped into readable
speaker-turn paragraphs, intelligence generated by the real provider, review page
loaded, and the correction path exercised on that real transcript.

**What that manual pass does not carry is a report.** Unlike Slice 4, which left
`docs/slice4-last-test-report.json`, this is an attestation: no artifact, nothing
re-runs it, and which individual correction behaviours were exercised is not
itemized. See L-41 before citing it for anything narrower than "it works".

### The three phases

Re-sequenced 2026-09-08. Read `docs/IMPLEMENTATION_PLAN.md` v1.3 before picking
up work.

- **Phase A — now.** Slice 6A: harden the single-user product on M1 + MLX.
  **Slice 6R: make the transcript readable** — added 2026-09-09, sequenced ahead
  of 6A's last item.
- **Phase B.** Slice 6B: `moshi-server` on a dedicated NVIDIA host, and measure
  the production serving path. Blocked on hardware, not on code.
- **Phase C.** Slice 6C: four participants, original Slice 6 exit gate intact.

**Slice 6 was split, not reduced.** The plan carries tables mapping every
original item and exit-gate clause into exactly one of 6A/6B/6C.

### What to do next

**Slice 6R is done and validated on the M1.** The transcript groups into
speaker-turn paragraphs (`review/paragraphs.ts`), interim text is marked by a
word not a colour, failed vs extracted-nothing summaries are distinct states, and
segments can be corrected — **additively**: `text` and `words` are never
overwritten, a correction lands beside them (migration `0002`), and every reader
goes through `transcript/corrections.py`, which is the single definition of what
a segment says. Correcting bumps `transcript_version`; the review page then says
*à revoir* and offers one button. Regeneration is **never** automatic.

**So there is exactly one item left in Phase A, and it is unstarted:**

1. **The remaining §15 metrics**, with a stated reason each. The spec lists them
   (`meetings_active`, `audio_frames_received_total`,
   `transcript_first_word_latency_ms`, ~twenty more); `/livez`, `/readyz` and
   `/health/deps` already exist, so this is the counters-and-histograms half.
   **The "stated reason each" is the deliverable, not a formality** — a metric
   nobody can name a use for is a metric nobody reads. Done when each emitted
   metric has a one-line reason and a test that it moves when the thing it
   measures happens. Start at `PROJECT_STATE.md` §12 item 1.
2. ~~**Degraded-state UX.**~~ **Done 2026-09-09** — `frontend/e2e/degraded.spec.ts`
   (6 specs). It found a real bug on the way (L-35), which is what the item was
   for. The **join** path still has the same shape and is deliberately not
   fixed — see `PROJECT_STATE.md` §12 before touching it.
3. ~~**The full-lifecycle test.**~~ **Done 2026-09-09** —
   `backend/tests/integration/test_full_lifecycle.py`, ✅ fake. Create → join →
   speak → end → finalize → summarize → review as one walk, on
   `MeasuredRecognizer` over a `LocalAudioStore`, plus a second meeting through
   the same process. What it does not cover is `PROJECT_STATE.md` L-34.

**Needs Aymen's M1, do not attempt in a sandbox:** real-time factor, first-word
and final-segment latency, memory growth, long-run MLX stability. One long
`tools/replay run … --speed 1` against MLX produces the first three from the
report it already writes; only the last needs duration.

### Decisions already made — do not re-litigate these

| Decision | Status |
|---|---|
| **L-28** — the orphaned sentence-final word, 8 of 30 | **Deferred by Aymen.** Do not reopen unprompted. `tests/unit/test_l28_orphaned_final_word.py` pins its shape; it asserts behaviour that is *wrong*, on purpose. Do not encode its suspected cause anywhere — that is still a hypothesis. |
| **Q2 — LLM provider** | OpenAI `gpt-4o-mini`, chosen on available credit. **The EU-residency half is still open** and is a product/legal call, not an engineering one. |
| **Q9 — transcript corrections** | **In scope, built and validated on M1 2026-09-10.** **Additive only:** raw ASR text and word timings are never overwritten, or L-28, the WER and every `[measure]` row become unfalsifiable. Correcting marks the summary *à revoir* and offers a button — it never re-runs the LLM by itself. No correction history (L-39) and no timestamp correction (L-40), both deliberate. |
| **L-33 — search is not ILIKE** | Deliberate. §6 says "ILIKE for now"; `ILIKE` is accent-sensitive and this is a French-first product. Matching is accent-insensitive, in Python, meeting-scoped. |
| **Phases A/B/C** | The sequencing above. Four participants are postponed, not dropped. |

### What is verified, and where

`PROJECT_STATE.md` §0 carries the vocabulary. The short version:

- ✅ **M1 + MLX** — the Slice 4 transcription run, `/readyz` against real weights,
  and the manual end-to-end meetings of 2026-09-08 and 2026-09-10. The second one
  covers Slice 6R: grouped paragraphs and the correction path on a real French
  transcript. Attested, not reported — L-41.
- ✅ **fake** — everything the automated suite covers, including
  `MeasuredRecognizer`, which replays *real* MLX emission timing (p50 320 ms,
  p95 1 280 ms, max 24 s between words) without needing a model.
- ⚠ — the health banner's failure states; Slice 5's rejection rate and cost.
- ❌ **needs NVIDIA** — `moshi_server`, `EndOfTurnEvent`, A-3, A-16, the GPU half
  of A-9.
- ❌ **needs cross-network** — A-8. Every run so far is loopback.

**Never mark the production GPU serving path verified until it has actually
served a meeting.** A number measured on MLX does not describe CUDA (A-16).

---

## Known traps

Seven lessons this codebase has actually paid for. Six are mistakes it made; the first is the one it avoided by applying the sixth in advance. Each cost real debugging time
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

**One fact, one definition — or the copies drift.** "What this segment says"
has three readers: the review page, `?q=` search, and the summarizer's prompt.
Corrections (Q9) made the answer stop being `segment.text`, and each reader
computing it for itself would mean a correction visible on screen and absent
from the summary. It lives once, in `transcript/corrections.py`, in
`transcript/` rather than beside the API because `jobs/` and `intelligence/` may
not import a transport (D-04). The same instinct as the trap below, applied
before the bug rather than after it.

**A tested value with no consumer is not a tested feature.** `bannerFor`
computed `canStartMeeting`, `status.test.ts` asserted it six times, and nothing
read it — so with the ASR runtime down the app said *Service indisponible* and
left **Nouvelle réunion** clickable (L-35). Every unit test was green: both
halves were right and nothing tested the join. Found by a person on the M1, not
by the suite. When a module exports a decision, grep for who acts on it; when two
components need the same fact, give them one copy of it, because a second poll is
how a banner and a button come to disagree.

**A model's clock can run ahead of its own words.** On the first real fixture the
silence tick closed 8 of 30 segments where the audio has only a 160-560 ms gap,
orphaning each sentence's last word — and WER scored 1.43% straight through it.
The suspected cause is emission lag outrunning `transcribed_offset_ms`; that is
inferred, not observed (L-28). Judge segmentation by looking at boundaries, never
by a word-level score.

