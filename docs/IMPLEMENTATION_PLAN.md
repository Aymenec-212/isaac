# Mosaïque — Implementation Plan

**Version:** 1.2 (prototype scope restored)
**Date:** 2026-09-03

**Normative source:** Technical Specification v0.1 §18. This plan re-cuts that sequence into vertical slices; it does not change its scope. Future-architecture work (external platform ingress, LiveKit) is **not in this plan** — see `mosaique-future-media-plane-options.md`.
**Method:** thin vertical slices. Every slice cuts through browser → gateway → runtime → ASR → database → UI and ends in something a person can watch happen.

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

## Slice 6 — Four participants, observability, load

**A person can:** run a four-person meeting, and an operator can see whether the system is healthy.

**Inside:** the remaining metrics from §15 with a stated reason each; `/readyz` and `/health/deps`; four-participant replay under load; queue and GPU-memory tuning against Spike C numbers; transcript search (FR-10).

**Exit gate:** four-participant 30-minute replay with < 2% dropped frames and latency budgets met; all eight tech spec §1.3 success criteria mapped to named passing tests; every `[measure]` row in the ledger has a real number.

**This is the end of the prototype.** Slice 7 is the gate for real customer data.

---

## Slice 7 — Pilot hardening

**Inside:** magic-link host auth and guest links (Q4); rate limits; `DELETE /meetings/{id}` plus the retention job (Q3); the §13.5 security checklist; graceful shutdown and drain; the eleven ADR files; runbook; alerts (Q8 deployment target).

**Exit gate:** security checklist green; tenant-isolation suite green; documented incident path; rollback tested; legal position on A-11 confirmed by counsel before any real customer conversation is recorded.

---

## Critical path and parallelism

```text
Slice 0 ─► Slice 1 ─► Slice 2 ─► Slice 3 ─► Slice 4 ─► Slice 5 ─► Slice 6 ─► Slice 7
                                              ▲          ▲
Spike B ─► Spike C ───────────────────────────┘          │
Spike D ─────────────────────────────────────────────────┘
Spike A ── informational, any time
```

Slices 0–3 have no external dependency: no GPU, no vendor, no answer to Q2. If Q2 stays open for weeks, the product path still reaches "working meeting on fake ASR with full failure handling", which is the honest majority of the engineering work.

---

## What would make me change this plan

- **Spike A shows heavy cross-talk even with headphones.** Then attribution needs cross-stream suppression, and that becomes a new slice between 2 and 3 rather than a footnote.
- **Spike B contradicts the audio format.** Slice 1's worklet and frame size change before Slice 1 ships, not after — which is why Spike B should start now even though Slice 4 is far away.
- **Spike B shows `moshi-server` cannot serve concurrent independent streams.** Then Slice 4 uses an in-process PyTorch adapter inside `asr-runtime` instead. The app-server is unchanged — that is what the adapter seam is for.
- **Spike B shows the model retracts emitted text.** Then §9.3's segmenter and the client reconciler's revision rules both get more work, and X-14's append-only invariant is withdrawn.
- **Slice 4 shows French WER on real meeting audio is unusable.** Then ADR-03 reopens. This is the single largest technical risk left in the prototype.
- **A trigger condition in ADR-12 §5 fires** — a pilot customer refuses to have guests run Mosaïque, or the product needs to speak in a meeting. Then a platform ingress becomes a real slice, added behind the D-04 seam. Not before.
