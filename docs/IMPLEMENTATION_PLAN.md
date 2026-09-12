# Mosaïque — Implementation Plan

> **Current amendment — 2026-09-12:** [Two-user voice / Azure ASR architecture](two-user-cloud-architecture.md)
> records the maintainer's new priority and supersedes companion-only D-01/ADR-01,
> the WebRTC exclusion and older single-user-first sequencing where they conflict.
> Direct WebRTC/TURN carries voice; the existing PCM WebSocket and ASR seams remain.
> Work proceeds one slice, one documented PR, review/merge, then the next slice.
> R0 merged as PR #19. [R1 deployment configuration](r1-azure-deployment.md) is ready
> for review; Azure GPU feasibility is blocked and no resources are deployed.
> Historical text below retains its evidence; use root PROJECT_STATE.md for next work.

**Version:** 1.4 (Slice 6R added to Phase A — 2026-09-09)
**Date:** 2026-09-03, re-sequenced 2026-09-08, extended 2026-09-09

**Normative source:** Technical Specification v0.1 §18. This plan re-cuts that sequence into vertical slices; it does not change its scope. Future-architecture work (external platform ingress, LiveKit) is **not in this plan** — see `mosaique-future-media-plane-options.md`.
**Method:** thin vertical slices. Every slice cuts through browser → gateway → runtime → ASR → database → UI and ends in something a person can watch happen.

---

## Phases: what is being built now, and what is being deferred

Added 2026-09-08. Slices 0–5 shipped in order and are unaffected. What changed is
the **order of what remains**, decided after Slice 5: the product is proven end to
end for one participant on hardware that exists, and the four-participant goal is
gated on hardware that does not. Rather than let the second stall the first, the
remaining work splits into three phases.

**Nothing is removed. Slice 6's requirements are re-sequenced, not reduced.**

| Phase | Runtime | Objective | Status |
|---|---|---|---|
| **A — Local single-user product** | M1 + MLX Kyutai | One person can reliably conduct a complete meeting locally and trust the transcript and the meeting intelligence. Repeatably, not once — and **read it**, which is Slice 6R. | **CURRENT FOCUS** — 6A five of six items done, 6R next |
| **B — GPU / production ASR validation** | dedicated NVIDIA + `moshi-server` | Prove the production serving path and measure it: GPU memory, real-time factor, p50/p95 latency, sustained stability, concurrent capacity, 1/2/4-participant behaviour. | Blocked on hardware |
| **C — Four participants** | the Phase B runtime | Demonstrate the original four-participant requirement and the rest of Slice 6's concurrency and load criteria. | Blocked on Phase B |

**Why this order.** Phase A's work — search, health endpoints, degraded-state UX,
lifecycle tests, long single-user runs, and now the review experience (6R) — is
product work that needs no GPU and was being held behind an infrastructure
purchase. Phase B's measurements cannot
be simulated and must not be guessed. Doing A first means the thing being
deployed onto a GPU in Phase B is already known to work.

**What this is not.** It is not a decision that four participants are out of
scope, and not a claim that MLX is the production runtime. MLX serves one stream
per process by design (L-26); that is sufficient for Phase A and disqualifying
for Phase C, and both remain true.

**The architecture does not move with the phases.** The seam is the whole point:

```text
Application → StreamingRecognizer → ASR implementation

  Phase A (now):     Application → StreamingRecognizer → Kyutai MLX
  Phase B/C (later): Application → StreamingRecognizer → Kyutai adapter
                                                       → moshi-server → NVIDIA GPU
```

Swapping the runtime must not touch the meeting domain, the transcript domain, or
any product-facing API. `tests/unit/test_architecture.py` fails the build if it
would.

---

## How this plan works

Each slice states: what a person can do at the end of it, what is inside, what is deliberately outside, and the exit gate. A slice is finished when its exit gate is green **and** `PROJECT_STATE.md` has been updated to say so.

Three rules that shape the order:

1. **Fakes before models.** `FakeRecognizer` and `FakeLLMProvider` carry the first three slices. This is the payoff of the adapter seam: the entire product path is demonstrable and testable before the GPU question (Q2) is answered.
2. **The replay harness is a tool, not a deliverable.** It arrives in Slice 2, before reconnect handling in Slice 3, because debugging realtime failures by asking someone to talk again does not work.
3. **Spikes run in parallel and produce one page of findings each.** They are timeboxed and do not block slices that use fakes.

---

## Spikes (parallel, timeboxed, do first where possible)

| # | Spike | Timebox | Answers | Blocks |
|---|---|---|---|---|
| **B** | **Kyutai verification (= PRD Stage 1).** Run one local stream from a microphone through `moshi-server`. The model card facts are already confirmed (blueprint D-05); what remains is whether it serves **concurrent independent streams** cleanly, and whether emitted text is ever **retracted**. | 1 day | A-3, and the second half of A-2. Confirms or breaks the §9.2 adapter decision. | Slice 4 |
| **C** | **Inference feasibility, reduced.** Vendor figures suggest large headroom, so this is confirmation rather than discovery: concurrency and memory on the actual GPU, and whether CPU-only is viable for development. | half day, after Q2 | A-4. | Slice 4, Slice 6 |
| **D** | **Token budget.** Synthesize a 60-minute 4-person French transcript; count tokens against the candidate provider's context window. | 2 hours | A-5. Whether chunk-and-merge is Slice 5 work or later. | Slice 5 |
| **A** | **Cross-talk characterisation.** Two laptops, one on speakerphone, one on headphones. Measure how much of the far end leaks into the near microphone. Informational: it tells us what to put in the join UI. | 2 hours | A-1. | **Nothing.** Does not gate a slice. |

**Spike B first.** It is the only one that can break a decision already made — the `moshi-server` adapter in §9.2 — and Slice 4 depends on it. Everything before Slice 4 runs on `FakeRecognizer` regardless, so B can run in parallel with Slices 0–3 rather than ahead of them.

Spike A is informational and can happen any time. Spike C waits on Q2. Spike D is an hour of work before Slice 5.

**Not in this plan:** the platform-ingress and LiveKit investigations (N-1…N-7 in ADR-12). They are future-architecture work, they gate nothing here, and they start only when one of ADR-12 §5's trigger conditions is met.

---

## Slice 0 — Walking skeleton

**A person can:** open the app, click "New meeting", and see the meeting appear in a list that survives a restart.

**Inside:** repo skeleton per spec §3; Docker Compose with app-server + PostgreSQL; typed config that fails fast; Alembic migration 1 with all eight tables including `organization_id`; seeded organization and pilot host account; `POST /meetings`, `GET /meetings`, `GET /meetings/{id}`; React app with a typed client generated from OpenAPI; `/livez`; CI running lint, types, and tests.

**Outside:** audio, WebSocket, ASR, intelligence, real auth.

**Exit gate:** `docker compose up` from a clean checkout produces a working app. Integration test creates a meeting and reads it back. Cross-tenant read test fails closed. CI green.

**Why first:** it proves the toolchain and the tenancy scaffolding before anything interesting depends on them, and it is a day of work, not a week.

---

## Slice 1 — One participant, end to end, on fakes

**This is the slice the whole plan is built around.** It proves the product spine before a single model dependency exists.

**A person can:** create a meeting, open the join link, accept the consent notice, grant microphone permission, speak, watch French text appear live and then firm up into final segments, click "End meeting", and land on a review page showing a summary, decisions, and action items — all produced by fakes, all persisted, all surviving a page reload.

**Inside:**
- Join flow: consent notice before the microphone prompt, display name, headphone guidance (blueprint C4), invite token → session token.
- `AudioWorkletProcessor`: 48 kHz float → 24 kHz s16le mono, 80 ms frames, RMS level meter.
- WebSocket gateway: `hello` authentication, binary frame codec, frame validation (§8.3), rejection counters.
- `ParticipantSession` with the bounded queue; the D-02 timeline model including silence padding on `seq` gaps.
- `FakeRecognizer`: emits scripted `WordEvent`/`EndOfTurnEvent` from a fixture, on a timer, with configurable delay — deterministic and fast-forwardable.
- Segmenter (§9.3), pure and unit-tested.
- Live transcript UI with visually distinct interim and final text; client reconciler on `(participant_id, sequence)` + `revision`.
- Final-segment persistence with `ON CONFLICT DO NOTHING`; raw PCM written to the audio store.
- `POST /end`: idempotent, drain, flush, COMPLETED, insert job.
- Job processor as an in-process task; `FakeLLMProvider`; schema validation; review page.
- Four metrics only (blueprint R-9); structured logging with correlation IDs.

**Outside:** more than one participant, reconnect, `ping`/`pong`, `stream.status`, real ASR, real LLM, audio scrubbing, search, magic-link login, the other twenty metrics.

**Exit gate:**
- E2E test (Playwright, synthetic microphone, fake ASR + fake LLM): create → join → speak → live transcript visible → end → review page populated.
- Unit tests: state machine, segmenter, reconciler, frame codec, authorization matrix, output schema including invalid `evidence_segment_ids`.
- Integration test: `POST /end` twice yields one COMPLETED meeting and one job.
- Restart test: kill app-server mid-meeting, restart, already-final segments are still there.
- Measured and recorded in the ledger: A-7 worklet CPU cost.

**Why this shape:** every remaining slice adds robustness, participants, or real models to a path that already works. Nothing later requires re-architecting this spine.

---

## Slice 2 — Two participants and the replay harness

**A person can:** join the same meeting from two browsers and see one merged transcript, correctly attributed, in both.

**Inside:** broadcast to all sockets in a meeting; participant panel with join/leave and speaking indicator; cross-participant display ordering by `start_ms`; `tools/replay` harness v1 — N PCM fixtures, timing script, speed factor, JSON report with per-segment first-word latency.

**Outside:** reconnect, overload behavior, four participants.

**Exit gate:** replay harness drives two streams and asserts the merged transcript; both participants' browsers show identical content; one real cross-network test between two physical machines (A-8); Spike A findings written up and the join-page guidance updated to match.

---

## Slice 3 — Failure behavior

**A person can:** lose their network for ten seconds, come back, and continue the same meeting with no duplicated or missing transcript — and always know from the UI whether the system is actually capturing audio.

**Inside:** `ping`/`pong` and stale-socket detection; 30 s reconnect grace with sequence resume and client-side buffering; `SESSION_REPLACED` for a second tab; AudioSession close after 30 s idle per D-02; `audio.pause`/`audio.resume`; bounded-queue overload policy producing visible `gap` segments; `stream.status` UI states (listening / receiving / transcribing / delayed / unavailable); DB-unavailable buffering; FINALIZING startup recovery.

**Outside:** real ASR.

**Exit gate:** realtime suite covering injected disconnect with buffered frames, duplicate frames, out-of-order frames, ASR stall, two-tab replacement, and a 60-minute accelerated run for memory stability. Tech spec §14.1 failure matrix has a passing test per row that does not require a real model.

---

## Slice 4 — Real Kyutai

**A person can:** hold a real French conversation and read an accurate live transcript.

**Inside:** apply Spike B findings to §8.1 and §9.3 before writing the adapter; `asr-runtime` container; Kyutai adapter behind `StreamingRecognizer` with bounded reconnect backoff and `health()`; full latency decomposition instrumentation (`capture → gateway_recv → dequeue → asr_first_event → broadcast`); tune the segmentation thresholds against real French audio using the replay harness.

**Outside:** four-participant load, real LLM.

**Exit gate:** smoke test replays a 3-minute French fixture at real time against the real model; WER and p95 first-word latency measured and written into the ledger — replacing guesses with numbers; A-10 resolved; the fake recognizer still passes every earlier test, proving the seam holds.

**Blocked by:** Q2, Spike B, Spike C.

---

## Slice 5 — Real meeting intelligence

**A person can:** read a summary, decisions, and action items that are actually about their meeting, click any decision, and jump to the moment in the recording where it was said.

**Inside:** real `LLMProvider`; prompt builder emitting `[seg_id] Speaker (mm:ss): text`; strict schema validation with `evidence_segment_ids` existence checks; retries with backoff; `meeting.outputs.ready`; review page with evidence links; `GET /audio/{session_id}` with Range support; audio scrubbing (FR-11, arithmetic thanks to D-02); chunk-and-merge if Spike D says it is needed.

**Exit gate:** ten real meetings processed; schema-rejection rate measured (A-6); FR-11 navigation verified end to end; LLM outage test confirms the transcript and meeting state are unaffected.

**Blocked by:** Q2 (provider and residency), Q3 (audio retention).

---

## Slice 6 — split, 2026-09-08

The original Slice 6 mixed two kinds of work: things one person needs on a laptop,
and things that only a GPU can answer. They are separated below. **Every original
requirement appears in exactly one of 6A or 6C; none was dropped.**

Original inside, and where each part went:

| Original Slice 6 item | Now |
|---|---|
| the remaining §15 metrics, with a stated reason each | **6A** |
| `/readyz` and `/health/deps` | **6A** |
| transcript search (FR-10) | **6A** |
| four-participant replay under load | **6C** |
| queue and GPU-memory tuning against Spike C numbers | **6B** (measure) → **6C** (tune) |

Original exit gate, and where each clause went:

| Original clause | Now |
|---|---|
| all eight tech spec §1.3 success criteria mapped to named passing tests | **6A** for the seven a single participant can exercise; **6C** for the concurrency one |
| every `[measure]` row in the ledger has a real number | **split**: single-stream rows in 6A, GPU and concurrency rows in 6B |
| four-participant 30-minute replay, < 2% dropped frames, latency budgets met | **6C, unchanged** |

---

## Slice 6A — The single-user product, hardened (PHASE A — current)

**A person can:** run a real meeting on their own machine, repeatedly, and trust
what comes out — and when something is broken, see *which* thing is broken.

**Inside:** transcript search (FR-10); `/readyz` and `/health/deps` reporting each
dependency separately (database, ASR runtime, LLM provider); the remaining §15
metrics with a stated reason each; degraded-state UX for every dependency that
can be down; a long single-user run against the **real MLX runtime** rather than
the fake; and a full-lifecycle test — create, join, speak, end, finalize,
summarize, review — run end to end rather than in pieces.

**Outside, deliberately:** anything needing a second concurrent stream. That is
6C, and MLX cannot do it (L-26).

**Exit gate:** a realistic single-user meeting can be run repeatedly on M1 + MLX
with a trustworthy transcript and trustworthy outputs; search returns the right
segments; `/readyz` distinguishes each dependency being down; the seven §1.3
success criteria that do not require concurrency have named passing tests; every
single-stream `[measure]` row has a real number.

---

## Slice 6R — Single-user review hardening (PHASE A — next)

**Added 2026-09-09, at Aymen's direction, after PR #14.** Sequenced *before*
Slice 6B and 6C: "before moving on to the two users and serving the ASR model on
a CUDA runtime, we first need to prioritize the single user experience and
improve it." It is numbered **6R**, not 6D, because it belongs beside 6A in
Phase A — a number after 6C would imply it comes after four participants, which
is the opposite of the decision.

**It also re-sequences one item inside 6A.** The remaining §15 metrics are 6A's
last open item and are now deliberately *behind* this slice — item 8 of the
priority list Aymen gave, after the seven review items. 6A does not close until
they are done; it is waiting on 6R, not abandoned.

### The design principle

> Preserve the raw segment/word evidence internally, but present a human-readable
> transcript by default. That supports auditability without forcing every user to
> read the transcript like a stream of model events. — Aymen, 2026-09-09

This is a **presentation** rule, not a storage one. Nothing in ADR-05 changes:
only final segments are persisted, word timings are still stored, and the raw
ASR output remains the record. What changes is that the record stops being the
thing a person is shown by default.

The concrete failure it names: today `ReviewPage` renders one `<p>` per segment
with the speaker's name repeated on **every** one. Segments close on 1 200 ms of
silence (§9.3), so an hour of French is roughly **930 paragraphs**, each labelled
"Amina" — and 8 in 30 of them are a single orphaned word (L-28). That is a log,
not a transcript.

### Two modes, and why both stay

| Mode | Renders | Exists for |
|---|---|---|
| **Live view** (`LiveMeeting`) | word-by-word, interim text visibly provisional, updating as the model revises | Making latency and transcription activity **visible**. It is the debugging and auditing surface and it is *not* to be "cleaned up" — seeing the model work is the point. |
| **Review view** (`ReviewPage`) | finalized segments as readable sentences and paragraphs, grouped by speaker and by pause | Reading a meeting afterwards. Word-by-word rendering is tiring for normal review. |

### The eight items, with what already exists

Honest status first: **two of the eight are already built and working.** They are
in the list because grouping segments into paragraphs is exactly what would break
them, so here they are regression constraints rather than new work.

| # | Item | Status today | This slice |
|---|---|---|---|
| 1 | Readable finalized transcript | ❌ one `<p>` per segment, speaker repeated on each | **Build.** Group into paragraphs. |
| 2 | Interim vs final clearly distinct | ⚠ styled in the live view (italic, grey, border colour) — **colour and italics only**, no text label, and no browser test asserts a person can tell | **Harden.** Non-colour-dependent signal, asserted in a browser. |
| 3 | Speaker grouping and timestamps | ❌ grouping absent; timestamps exist only on evidence links | **Build.** |
| 4 | Clickable citations that seek audio | ✅ works — FR-11, `evidence.ts` (11), `playback.test.ts` (11), `test_audio_playback.py` (7), and the lifecycle test's citation→byte-range leg | **Must not regress.** Scroll targets are keyed to per-segment `<p>` nodes; grouping moves them. |
| 5 | Search highlights the matching phrase | ✅ works — FR-10, server-returned offsets, `highlight.test.ts` (12) | **Must not regress.** Spans index into a *segment's* text; a paragraph is several segments joined. |
| 6 | Graceful failed/degraded summaries | ⚠ `status: "failed"` renders one notice; a *partial* or low-confidence output has no state at all | **Harden.** |
| 7 | Manual correction or annotation | ❌ absent, and **Q9's standing default is "out of scope"** | **Build — and it changes Q9.** See below. |
| 8 | The remaining §15 metrics | ❌ 6A's last open item | **Not in this slice.** Explicitly after it. |

### Item 7 changes an open question, and the shape matters

Q9 — "are transcript corrections in scope?" — has carried the default **out of
scope** since 2026-09-03. Aymen's priority list includes manual correction, which
answers it. Recorded in `PROJECT_STATE.md` §3 as a decision with a date, not
absorbed silently.

**Corrections must be additive.** The raw ASR text is never overwritten:

* the original segment text and its word timings stay exactly as the model
  produced them — that is the auditability half of the design principle, and it
  is also what keeps `asr_version` meaningful and any future WER re-measurement
  possible;
* a correction is stored *alongside*, with its own authorship and timestamp;
* the review view shows the corrected text by default and can always reveal what
  the model actually said.

Destructive editing would make L-28, WER and every `[measure]` row unfalsifiable
after the fact, which is too high a price for a nicer paragraph.

**Open, and to be decided inside the slice rather than assumed:** whether
correcting a segment invalidates the meeting intelligence that cites it.
Outputs cite `evidence_segment_ids`, so a citation stays *resolvable* — the id is
unchanged — but the quoted sentence may no longer match what the summary claims.
Re-running the summary is a paid LLM call and a product decision; this slice does
**not** do it automatically.

**A person can:** open a finished meeting and read it the way they would read
minutes — paragraphs, speakers, timestamps — click a decision and hear the
moment, search and see the phrase highlighted, fix a word the model got wrong,
and still get to the raw model output when they want to audit it.

**Inside:** items 1, 2, 3, 6 and 7 above; items 4 and 5 held as regressions with
browser tests that fail if grouping breaks them.

**Outside, deliberately:**

* the remaining §15 metrics (item 8) — after this slice, still 6A's to close;
* anything needing a second concurrent stream (6C) or a GPU (6B);
* **re-running meeting intelligence over corrected text** — named above, decided
  in-slice, built later if at all;
* **gating the join path on readiness** — the L-35 sibling. Same bug shape, but
  refusing a participant who already holds an invite is its own product call and
  is still open;
* cross-meeting search (L-33) and L-28, both deferred by standing decision.

**Exit gate:**

1. An hour-long transcript renders as speaker-grouped paragraphs with
   timestamps, not one labelled line per segment — asserted by a test over a
   realistic segment count, not a three-segment fixture.
2. Interim and final text are distinguishable **without relying on colour**, and
   a browser spec asserts what a person sees.
3. Clicking a citation still scrolls to the right moment and still seeks the
   audio, with grouping in place — browser spec.
4. A search still highlights the matching phrase inside a grouped paragraph, at
   the right offsets — unit test over the join, plus a browser spec.
5. A failed summary and a degraded one each render a distinct, accurate state,
   and the transcript survives both.
6. A correction round-trips: raw text preserved and retrievable, corrected text
   shown by default, evidence still resolves, and a named test proves the
   original is still there afterwards.
7. `PROJECT_STATE.md` updated — Q9 answered, FR rows re-evidenced, new
   limitations recorded, changelog row appended.

---

## Slice 6B — GPU and production ASR validation (PHASE B)

**Blocked on:** a dedicated NVIDIA host. This is a procurement item, not an
engineering one, and it is the only thing standing between here and Phase C.

**A person can:** nothing new. This slice produces numbers, not features — which
is exactly why it must not be skipped or guessed at.

**Inside:** deploy `moshi-server` on the GPU host; point `asr_runtime` at it by
config alone (`MOSAIQUE_ASR_RUNTIME=moshi_server`, no code change — if any is
needed, the seam is broken and that is the finding); then measure, on the real
serving path: GPU memory usage; real-time factor; p50/p95 latency; sustained
streaming stability over a long run; concurrent stream capacity; and 1 / 2 / 4
participant behaviour.

Also closes what only this hardware can close: A-3, A-4, the GPU half of A-9,
A-16 (do MLX and CUDA transcripts agree?), and §9.3's `end_of_turn_threshold`,
which is dead code on MLX because the `-mlx` weights carry no VAD heads.

**Exit gate:** every number above measured and written into `PROJECT_STATE.md`
§8, each labelled with the runtime it was measured on. The production serving
path is **not** marked verified until it has actually served a meeting.

---

## Slice 6C — Four participants (PHASE C)

**A person can:** run a four-person meeting, and an operator can see whether the
system is healthy under that load.

**Blocked on:** Slice 6B.

**Inside:** four-participant replay under load; queue and GPU-memory tuning
against the Slice 6B numbers; the §1.3 concurrency success criterion.

**Exit gate — unchanged from the original Slice 6:** four-participant 30-minute
replay with < 2% dropped frames and latency budgets met; all eight tech spec §1.3
success criteria mapped to named passing tests; every `[measure]` row in the
ledger has a real number.

**This is the end of the prototype.** Slice 7 is the gate for real customer data.

---

## Slice 7 — Pilot hardening

**Inside:** magic-link host auth and guest links (Q4); rate limits; `DELETE /meetings/{id}` plus the retention job (Q3); the §13.5 security checklist; graceful shutdown and drain; the eleven ADR files; runbook; alerts (Q8 deployment target).

**Exit gate:** security checklist green; tenant-isolation suite green; documented incident path; rollback tested; legal position on A-11 confirmed by counsel before any real customer conversation is recorded.

---

## Critical path and parallelism

```text
        ┌──────────────── PHASE A: laptop ────────────────┐  ┌── PHASE B ──┐ ┌ PHASE C ┐
Slice 0 ─► 1 ─► 2 ─► 3 ─► 4 ─► 5 ─► 6A ─► 6R ─► 6A(§15 metrics) ─► 6B ─────► 6C ─► Slice 7
                          ▲     ▲                                 ▲
Spike B ─► Spike C ───────┘     │                                 │
Spike D ────────────────────────┘                    a dedicated NVIDIA host
Spike A ── informational, any time                   (procurement, not code)
```

Slices 0–3 have no external dependency: no GPU, no vendor, no answer to Q2. If Q2 stays open for weeks, the product path still reaches "working meeting on fake ASR with full failure handling", which is the honest majority of the engineering work.

**That reasoning is what the 2026-09-08 re-sequencing extends.** Everything up to
and including 6A runs on a laptop. The GPU is needed for exactly one thing —
concurrency — and it now gates only the slice that actually needs it, instead of
gating the product work queued behind it.

**2026-09-09 extends it once more, and the diagram above is deliberately odd.**
6A interleaves with 6R: five of 6A's six items are done, and its last one — the
§15 metrics — is sequenced *after* 6R at Aymen's direction, because a readable
transcript is worth more to a single user than a counter is. So 6A closes after
6R rather than before it. Written this way rather than tidied, because pretending
the slices are strictly ordered would misrepresent what is actually being built.

---

## What would make me change this plan

- **Spike A shows heavy cross-talk even with headphones.** Then attribution needs cross-stream suppression, and that becomes a new slice between 2 and 3 rather than a footnote.
- **Spike B contradicts the audio format.** Slice 1's worklet and frame size change before Slice 1 ships, not after — which is why Spike B should start now even though Slice 4 is far away.
- **Spike B shows `moshi-server` cannot serve concurrent independent streams.** Then Slice 4 uses an in-process PyTorch adapter inside `asr-runtime` instead. The app-server is unchanged — that is what the adapter seam is for.
- **Spike B shows the model retracts emitted text.** Then §9.3's segmenter and the client reconciler's revision rules both get more work, and X-14's append-only invariant is withdrawn.
- **Slice 4 shows French WER on real meeting audio is unusable.** Then ADR-03 reopens. This is the single largest technical risk left in the prototype.
- **Phase A finds a defect that makes the single-user product untrustworthy.** Then it is fixed inside 6A rather than deferred to the GPU phase, because Phase A's whole purpose is that one person can rely on the result. L-28 is the open candidate: deferred 2026-09-08 as an edge case, to be reassessed at the end of Slice 5 and only if it shows real impact on meeting outputs, evidence linking, or transcript correctness.
- **The GPU host arrives sooner than expected.** Phase A still finishes first. Deploying a product that has not been made reliable for one user onto four is how you get four unreliable users.
- **Phase B shows `moshi-server` needs application changes to swap in.** That is a seam failure and a finding in its own right — the config-only swap is the claim the architecture makes, and 6B is where it is tested for real.
- **A trigger condition in ADR-12 §5 fires** — a pilot customer refuses to have guests run Mosaïque, or the product needs to speak in a meeting. Then a platform ingress becomes a real slice, added behind the D-04 seam. Not before.
