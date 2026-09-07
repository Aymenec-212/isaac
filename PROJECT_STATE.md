# PROJECT_STATE.md

**Project:** Mosaïque — realtime meeting intelligence, French-first
**Last updated:** 2026-09-06 (rev 6 — Slice 2 complete except two field checks)
**Updated by:** Slice 2 implementation
**Current slice:** Slice 2 VERIFIED in software. Two exit-gate items need hardware
this environment does not have: the cross-network run (A-8) and Spike A.
**Maturity level (skill §41):** Level 1 — functional prototype, multi-participant, fake models

---

## 0. What this document is

This is the only document in the project that describes **reality**. Every other document describes intent.

The PRD says what the product should do. The technical specification says how it should be built. This file says what exists, what runs, and what has been proven to work. When they disagree, this file is right.

### Update rules

1. Update at the end of every slice, and whenever a status changes. A slice is not finished until this file reflects it.
2. **Never mark anything `VERIFIED` without naming the evidence** — a test id, or a measurement with a date. "I saw it work" is not evidence.
3. Never delete a row. Move it to `DEFERRED` or `REMOVED` with a reason.
4. New assumptions get added to §7 the moment they are made, not after they break.

### Status vocabulary

| Status | Means |
|---|---|
| `PLANNED` | Named in a document. No design detail. |
| `SPECIFIED` | Contract exists in the technical spec or blueprint. No code. |
| `IN PROGRESS` | Being built now. |
| `IMPLEMENTED` | Code merged and runs. **No test proves it.** Treat as unverified. |
| `VERIFIED` | A named automated test passes, or a number was measured and recorded here. |
| `DEFERRED` | Deliberately not built. Reason and revisit trigger recorded. |
| `BLOCKED` | Cannot proceed. Blocker named. |
| `REMOVED` | Was built, then taken out. Reason recorded. |

**Slices 0 and 1 are VERIFIED, browser tests included — the Playwright suite now
runs (L-12 closed). Slice 2 is VERIFIED in software: the replay harness, the
multi-participant runtime, and both browsers are covered by named tests. Two
items on its exit gate are NOT done and are not claimed: a real cross-network
run between two physical machines (A-8), and Spike A. Everything from Slice 3
onward is still `SPECIFIED`.**

---

## 1. Snapshot

| Field | Value |
|---|---|
| Repository | created; 4 commits on `main` |
| Runnable | yes — `docker compose up`, or uv + local PostgreSQL |
| Deployed | no |
| Real audio ever transcribed by this system | **no — every model in the path is a fake** |
| Tests passing | **137**: 85 backend unit, 32 backend integration (real PostgreSQL), 18 frontend unit, 2 Playwright browser specs |
| Lint / types | ruff clean; mypy strict clean on 73 source files (the harness included); `tsc --noEmit` clean |
| Known gap | A-8 unvalidated: every run so far is loopback on one machine. Spike A not run. **No CI runs on this repository** — see L-18. |
| Next action | the two field checks above, then Slice 3 — failure behavior |
| Next gate | Slice 3 exit: the tech spec §14.1 failure matrix, a passing test per row |

---

## 2. Locked decisions

| ID | Decision | Date | Recorded in |
|---|---|---|---|
| D-01 | Prototype ingress is browser capture over WebSocket. No LiveKit, no SFU, no platform integration. | 2026-09-03 | Blueprint §2.1 |
| D-04 | Minimal `MeetingIngress` seam so the ingress is replaceable later. One implementation, one enum column. | 2026-09-03 | Blueprint §2.1a |
| D-05 | Kyutai spec assumptions confirmed; flush trick adopted for segment-close latency. | 2026-09-03 | Blueprint §2.1b |
| ADR-12 | Media-plane options for later. **Non-normative — governs nothing.** | 2026-09-03 | `mosaique-future-media-plane-options.md` |
| D-02 | Meeting timeline derived from frame counts with silence padding; client clocks never trusted for ordering. | 2026-09-03 | Blueprint §2.2, ADR-11 |
| D-03 | "Verified" requires named test evidence. | 2026-09-03 | Blueprint §2.3 |
| ADR-01 | WebSocket + raw PCM; no LiveKit | 2026-09-03 | Tech spec §16.1 |
| ADR-02 | Python/FastAPI + React/TS | 2026-09-03 | Tech spec §16.1 |
| ADR-03 | Kyutai STT-1B behind `StreamingRecognizer`, separate process | 2026-09-03 | Tech spec §16.1 |
| ADR-04 | PostgreSQL for all durable state including the job queue | 2026-09-03 | Tech spec §16.1 |
| ADR-05 | Only final segments persisted | 2026-09-03 | Tech spec §16.1 |
| ADR-06 | Raw per-participant audio stored | 2026-09-03 | Tech spec §16.1, pending Q3 |
| ADR-07 | Intelligence async, derived, versioned, evidence-linked | 2026-09-03 | Tech spec §16.1 |
| ADR-08 | `organization_id` from migration 1 | 2026-09-03 | Tech spec §16.1 |
| ADR-09 | Single app-server process, four separable runtimes | 2026-09-03 | Tech spec §16.1 |

**ADR files written:** 0 of 12. Scheduled for Slice 7. ADR-12 exists as a standalone decision document.

---

## 3. Open questions

| # | Question | Owner | Blocks | Default in force | Status |
|---|---|---|---|---|---|
| Q10 | Who is the prototype piloted with, given every participant runs it? | product | **nothing — pilot recruitment only** | internal + consenting participants | OPEN, non-blocking |
| Q11–Q13 | Platform choice, build-vs-buy, product thesis | product | **nothing in the prototype** | — | DEFERRED to ADR-12 |
| Q2 | GPU location, inference host, EU data residency | product | Slice 4, Slice 5 | none | OPEN |
| Q3 | Raw audio retention and consent | product | Slice 5, Slice 7 | store, 30 days | OPEN |
| Q5 | Participant ceiling | product | Slice 6 | 4 | OPEN |
| Q4 | Pilot auth model | product | Slice 7 | magic link + guest links | OPEN |
| Q8 | Deployment target | product | Slice 7 | single VM + Compose | OPEN |
| Q6 | UI language | product | cosmetic | French only | OPEN |
| Q9 | Transcript corrections in scope | product | — | out of scope | OPEN |
| Q7 | Stack confirmation | product | all | as specified | OPEN |
| Q1 | Companion vs carrier | product | everything | — | **CLOSED 2026-09-03 → companion** |

---

## 4. Functional requirements — intended vs. real

| FR | Requirement (PRD §17) | Intended in | Status | Evidence | Notes |
|---|---|---|---|---|---|
| FR-01 | Meeting creation with unique ID | Slice 0/1 | **VERIFIED** | `test_create_meeting_then_read_it_back` | ULID; `organization_id` from migration 1 |
| FR-02 | Continuous microphone capture | Slice 1 | **VERIFIED** | `e2e/meeting.spec.ts`, `e2e/two-participants.spec.ts` (Chromium fake device) | AudioWorklet 48→24 kHz, 80 ms frames |
| FR-03 | Realtime transcription | Slice 1 (fake) / Slice 4 (real) | **VERIFIED (fake only)** | `test_speaking_produces_live_interim_then_final_segments` | Real ASR is Slice 4 |
| FR-04 | Interim and final events | Slice 1 | **VERIFIED** | `tests/unit/test_segmenter.py` (12), `reconciler.test.ts` (11), flow test asserts both statuses |
| FR-05 | Speaker association | Slice 2 | **VERIFIED (endpoint capture)** | `test_the_harness_merges_two_attributed_streams`, `e2e/two-participants.spec.ts` | Two streams, each segment under its own speaker, in both browsers. Attribution when one microphone hears another person is Spike A and is **not** covered (L-2) |
| FR-06 | Finalized transcript | Slice 1 | **VERIFIED** | `test_only_final_segments_reach_the_database`, `test_startup_recovery_completes_a_stranded_finalizing_meeting` |
| FR-07 | Meeting summary | Slice 1 (fake) / Slice 5 (real) | **VERIFIED (fake only)** | `test_processor_produces_evidence_linked_outputs` |
| FR-08 | Action item extraction | Slice 1 (fake) / Slice 5 (real) | **VERIFIED (fake only)** | same test; evidence ids checked against real segments |
| FR-09 | Decision extraction | Slice 1 (fake) / Slice 5 (real) | **VERIFIED (fake only)** | same test |
| FR-10 | Transcript review and search | read: Slice 1, search: Slice 6 | **read VERIFIED** | `GET /transcript` covered, ordered across participants by `start_ms`; search is Slice 6 |
| FR-11 | Timestamp navigation | Slice 5 | SPECIFIED | — | Made trivial by D-02 |

### Non-functional

| NFR | Target | Status | Evidence |
|---|---|---|---|
| First-word latency p95 | ≤ 2.0 s **[measure]** | UNMEASURED against the real target | 915 ms measured on the **fake** recognizer over loopback (§8). Not the NFR: no real model, no real network |
| Final-segment latency p95 | ≤ 3.5 s **[measure]** | UNMEASURED | — |
| Reliability: 10 s disconnect without duplication | pass | SPECIFIED | — (Slice 3; the harness that will inject the disconnect now exists) |
| Scalability: 4 concurrent participants | pass | PARTIAL | **2** pass: `test_the_harness_merges_two_attributed_streams`. 4 is Slice 6 |
| Privacy: consent, retention, deletion, log hygiene | defined | SPECIFIED | — |
| Tenant isolation | fail closed | **VERIFIED** | `test_cross_tenant_read_fails_closed`, `test_cross_tenant_list_is_empty`, `test_repository_scope_blocks_cross_tenant_get`, `test_every_tenant_owned_table_has_organization_id` |

---

## 5. Components

| Component | Spec ref | Status | Evidence |
|---|---|---|---|
| `config/` typed settings | §3 | **VERIFIED** | `tests/unit/test_config.py` (7 tests: missing key, short secret, wrong driver, unknown key, pilot guard) |
| `domain/` entities + state machine | §4, §5 | **VERIFIED** | `tests/unit/test_state_machine.py` (13 tests incl. idempotent `end`, no return from COMPLETED) |
| `app/api/` REST routers | §6 | **PARTIAL — VERIFIED for Slice 0 routes** | `tests/integration/test_meetings_api.py`. Only POST/GET `/meetings`, GET `/meetings/{id}`, `/livez` exist |
| `app/auth/` tokens + authorization | §13.1–13.2 | **VERIFIED** | `tests/unit/test_authorization.py` (11 tests). Magic-link login still deferred (R-2) |
| `realtime/gateway/` WS endpoint | §7 | **VERIFIED** | `test_websocket_refuses_audio_before_a_valid_hello`, flow tests |
| `realtime/protocol/` schemas + frame codec | §7.1–7.2 | **VERIFIED** | `tests/unit/test_frame_codec.py` (7) |
| `realtime/sessions/` ParticipantSession | §7.4 | **VERIFIED** | `tests/unit/test_participant_session.py` (11) |
| `realtime/sessions/` MeetingRuntime roster + speaking | Slice 2 | **VERIFIED** | `test_the_runtime_announces_the_roster_and_who_is_speaking` |
| `realtime/ingress/` MeetingIngress protocol | Blueprint D-04 | **VERIFIED** | `test_architecture.py` parses every downstream module for transport imports |
| `speech/interfaces/` StreamingRecognizer | §9.1 | **VERIFIED** | `test_fake_and_kyutai_adapters_satisfy_the_same_protocol` |
| `speech/adapters/fake/` | §9.1 | **VERIFIED** | drives all Slice 1 and Slice 2 flow tests |
| `speech/adapters/kyutai/` | §9.2 | SPECIFIED | — | Slice 4 |
| `transcript/segmenter.py` | §9.3 | **VERIFIED** | `tests/unit/test_segmenter.py` (12) |
| `intelligence/` LLMProvider + schema | §12 | **VERIFIED** | `tests/unit/test_output_schema.py` (7) |
| `persistence/` models, repos, migrations | §4 | **VERIFIED** | migration `0001` applies from empty; `test_all_eight_tables_exist_in_migration_one`, `test_meeting_survives_a_new_session` |
| `jobs/` processor loop | §12.1 | **VERIFIED** | `tests/integration/test_intelligence_flow.py` (7): retry, failure isolation, no duplicate outputs |
| `observability/` metrics + logging | §15 | PARTIAL | Four R-9 metrics implemented in-process. No Prometheus exporter until Slice 6 |
| `tools/replay/` harness | §14.3 | **VERIFIED** | `tests/integration/test_replay.py` (4). Drives the real gateway over a real WebSocket against an app-server in its own process |
| Frontend `audio/` worklet | §8.2 | **VERIFIED** | `e2e/meeting.spec.ts` streams through it from Chromium's fake device |
| Frontend `realtime/` reconciler | §7.3 | **VERIFIED** | `src/realtime/__tests__/reconciler.test.ts` (11), including cross-participant ordering |
| Frontend `realtime/` roster | Slice 2 | **VERIFIED** | `src/realtime/__tests__/roster.test.ts` (7) |
| Frontend `meeting/ParticipantPanel` | Slice 2 | **VERIFIED** | `e2e/two-participants.spec.ts` asserts both names and the speaking state |
| Frontend `realtime/` WS client | §7 | **VERIFIED** | both e2e specs |
| Frontend `api/` typed client | §3 | **VERIFIED** | Generated by `openapi-typescript` from `openapi.json`; CI fails on drift |
| Frontend meeting list + token gate | §3 | **VERIFIED** | `e2e/meeting.spec.ts` creates a meeting through the UI |
| Frontend `meeting/` join + live view | PRD §7 | **VERIFIED** | both e2e specs |
| Frontend `review/` | PRD §9 | **VERIFIED** | `e2e/meeting.spec.ts`; `e2e/two-participants.spec.ts` checks both speakers survive into it |

---

## 6. Contracts

### HTTP routes

| Route | Status | Slice |
|---|---|---|
| `POST /meetings` | **VERIFIED** | 0 |
| `POST /meetings/{id}/join` | **VERIFIED** | 1 |
| `GET /meetings/{id}` | **VERIFIED** | 0 |
| `POST /meetings/{id}/end` | **VERIFIED** | 1 |
| `GET /meetings/{id}/transcript` | **VERIFIED** | 1 |
| `GET /meetings/{id}/outputs` | **VERIFIED** | 1 |
| `GET /meetings` | **VERIFIED** | 0 |
| `GET /meetings/{id}/audio/{session_id}` | SPECIFIED | 5 |
| `DELETE /meetings/{id}` | SPECIFIED (amendment A-6) | 7 |

### WebSocket messages

Slice column indicates first working implementation.

| Message | Slice |
|---|---|
| `hello` / `hello.ok` | 1 — **VERIFIED** |
| binary audio frame | 1 — **VERIFIED** |
| `transcript.delta` | 1 — **VERIFIED** |
| `transcript.segment.final` | 1 — **VERIFIED** |
| `meeting.state` | 1 — IMPLEMENTED. Published on end, but nothing asserts a client acts on it |
| `error` | 1 — **VERIFIED** |
| `ping` / `pong` | 3 |
| `participant.joined` / `participant.left` | 2 — **VERIFIED** (`test_the_runtime_announces_the_roster_and_who_is_speaking`) |
| `participant.reconnecting` | 3 |
| `participant.speaking` | 2 — **VERIFIED** (same test; `roster.test.ts` covers the client half) |
| `stream.status` | 3 |
| `audio.pause` / `audio.resume` | 3 |
| `meeting.outputs.ready` | 5 |

### Database tables

All eight — `Organization`, `User`, `Meeting`, `Participant`, `AudioSession`, `TranscriptSegment`, `MeetingOutputs`, `Job` — **MIGRATED** in revision `0001`. Amendments A-5 (Job.meeting_id FK, MeetingOutputs has no status) and D-04 (`Meeting.source_kind`) are applied. `AudioSession.epoch_ms` is present for the D-02 timeline but unused until Slice 1.

---

## 7. Assumption register

Mirrors blueprint §5. Status here is the live one.

| # | Assumption | Risk if false | Validated by | Status |
|---|---|---|---|---|
| A-1 | Browser AEC suppresses far-end audio from another app | Prototype meetings need headphones | Spike A (informational) | UNVALIDATED, non-blocking. Needs two machines and real microphones; the join page still carries the Slice 1 headphone guidance unchanged |
| A-2 | Kyutai: 24 kHz, 80 ms, word timestamps, semantic VAD, no retraction | Audio format + segmenter change | Spike B | **MOSTLY CONFIRMED (D-05)** — retraction still open |
| A-3 | `moshi-server` handles concurrent streams | Fall back to PyTorch adapter | Spike B | UNVALIDATED — **now the main Spike B question** |
| A-4 | One GPU sustains 4 real-time streams | Ceiling and cost change | Spike C (half day) | **LARGELY ANSWERED** — vendor figure ~400 real-time streams per H100; confirm on our hardware |
| A-12 | Flush trick available through the adapter | Final-segment latency reverts to model delay | Slice 4 | UNVALIDATED |
| A-5 | 60-min transcript fits one LLM context | Chunking moves into Slice 5 | Spike D | UNVALIDATED |
| A-6 | LLM returns valid `evidence_segment_ids` | Evidence linking softens | Slice 5 | UNVALIDATED |
| A-7 | Worklet resampling is cheap on mid-range laptops | Resample server-side | Slice 1 | UNVALIDATED — the e2e runs the worklet but measures no CPU cost |
| A-8 | 12.5 frames/s per participant survives real networks | Batch or enlarge frames | Slice 2 | **UNVALIDATED — the one Slice 2 exit-gate item still open.** Every run so far is loopback on one machine. `tools/replay --base-url` against a second machine is the test; it has not been run |
| A-9 | 30 s ASR grace does not leak GPU memory | Shorten grace | Slice 3 | UNVALIDATED |
| A-10 | French WER is good enough to be useful | Model swap | Slice 4 | UNVALIDATED |
| A-11 | "Joining is consent" satisfies FR/EU law | Consent flow and DPA change | legal counsel | **UNVALIDATED — not an engineering question** |
| A-13 | A participant's place on the meeting timeline may be anchored to the server clock at connect | A replay cannot reproduce a staggered join; joins would need to be frame-derived too | Slice 2 | **CONFIRMED as a property, not a guess** — see L-15. Segmentation is frame-derived and speed-invariant; the join anchor is not |

---

## 8. Measured values ledger

Every `[measure]` placeholder in the technical specification. A value here means it was measured, on a date, by something named.

| Parameter | Current value | Source | Status |
|---|---|---|---|
| First-word latency p95 target | 2.0 s | guess | UNMEASURED |
| Final-segment latency p95 target | 3.5 s | guess (blueprint X-4) | UNMEASURED |
| Reconnect grace | 30 s | guess | UNMEASURED |
| ASR event timeout | 5 s | guess | UNMEASURED |
| End-of-turn probability threshold | 0.5 | guess | UNMEASURED |
| Silence threshold for segment close | 700 ms | guess | UNMEASURED |
| Segment duration cap | 15 s | guess | UNMEASURED |
| Finalize drain deadline | 20 s | guess | UNMEASURED |
| Outputs ready after end | 90 s | guess | UNMEASURED |
| Queue depth: normal / lagging / full | 25 / 62 frames | guess | UNMEASURED |
| Sustained-overload stream failure | 15 s | guess | UNMEASURED |
| Idle timeout closing AudioSession | 30 s | derived from D-02 | UNMEASURED |
| Concurrent streams per GPU | ~400/H100 (vendor figure) | Kyutai docs | UNCONFIRMED ON OUR HARDWARE |
| Replay realised speedup at `--speed 10` | 4.17x — 20 s of stream in 4.8 s wall | `tools/replay`, 2 streams, 2026-09-06 | MEASURED. The ceiling is the harness pacing and loopback, not the runtime |
| First-word latency p95, 1x, 2 participants | 915 ms | replay report, 2026-09-06 | MEASURED — **fake recognizer over loopback**. Dominated by the fake's 500 ms scripted model delay. Not the NFR and not a prediction of it |
| Pipeline turnaround p95 (frame out → interim text back), 1x | 962 ms | same report | MEASURED, same caveat |
| Pipeline turnaround p95 at 10x | 98 ms | same report | MEASURED. Lower because the fake's model delay is stream time, which compresses |
| Frames dropped, 2 participants at 10x | 0 of 250 per stream | `audio_sessions.frames_dropped` after a CLI replay, 2026-09-06 | MEASURED on loopback. A-8 is about real networks and is still open |
| Segment-close latency with vs. without flush trick | unknown | — | UNMEASURED |
| French WER on real meeting audio | unknown | — | UNMEASURED |
| Cross-talk misattribution rate (speakerphone) | unknown | — | UNMEASURED |

---

## 9. Test inventory

| Suite | Covers | Status |
|---|---|---|
| `tests/unit/` | state machine, config, authorization, segmenter, frame codec, participant session, output schema, **architecture boundaries** | **85 passing** |
| `tests/integration/` | create/read/list, tenancy, durability, join, live transcript, end idempotency, job retry, failure isolation, startup recovery | **28 passing** |
| `tests/integration/test_replay.py` | two streams merged and attributed; 1x ≡ 10x; roster and speaking; report shape | **4 passing** — runs a real app-server subprocess and drives it over real WebSockets |
| `frontend src/**/*.test.ts` | transcript reconciler (11), participant roster (7) | **18 passing** (vitest) |
| `e2e/meeting.spec.ts` | full single-participant browser flow with a fake microphone | **1 passing** (L-12 closed) |
| `e2e/two-participants.spec.ts` | two browsers, merged attributed transcript, roster, speaking indicator | **1 passing** |
| `tests/realtime/` | disconnect, duplicates, ASR stall, long-run memory | NOT WRITTEN — Slice 3 |
| smoke (real model) | WER + latency on French fixture | NOT WRITTEN — Slice 4 |
| cross-network run (A-8) | two physical machines, one meeting | **NOT RUN** — needs a second machine. `tools/replay --base-url` is the harness for it |
| Spike A | cross-talk with a speakerphone | **NOT RUN** — needs two laptops and real microphones |

---

## 10. Known limitations and accepted debt

Current, as of planning. Each is a deliberate choice, not an oversight.

| # | Limitation | Accepted because | Revisit when |
|---|---|---|---|
| L-1 | Every participant must run Mosaïque | Prototype scope: participants are known and consenting | ADR-12 trigger conditions |
| L-2 | Headphones recommended for reliable attribution | Endpoint capture limit; acceptable at Level 1 | Spike A result |
| L-10 | No external conferencing-platform integration | Out of prototype scope by D-01 | ADR-12 trigger conditions |
| L-3 | Single host; no horizontal scale | Prototype | Concurrent meetings exceed one host |
| L-4 | Deployment during a live meeting drops it | Level 1 limitation, spec §14.1 | Level 2 |
| L-5 | No transcript editing | Q9 default | Product asks |
| L-6 | No billing or usage accounting | Skill §44 step 13 out of scope | Monetization |
| L-7 | No multi-language | French-first | Darija roadmap |
| L-8 | Prompt-injection defense is Level 1 only | Spec §12.4 | Enterprise pilot |
| L-9 | Search is ILIKE, not indexed | Prototype scale | Meeting count grows |
| L-11 | Host token is pasted by hand into the UI | Slice 0 stands in for login (R-2) | Slice 7 magic link |
| L-12 | ~~Playwright e2e written but never executed~~ **CLOSED 2026-09-06** | Both browser specs now run and pass. `MOSAIQUE_CHROMIUM_PATH` points them at a pre-installed Chromium where `playwright install` cannot reach the network | — |
| L-13 | ~~The segmenter sometimes splits one spoken phrase into two segments~~ **CLOSED 2026-09-06** | It was not a threshold problem. The frame pump was still ticking the segmenter with `stream_offset_ms` — audio *pushed* — while the reader ticked correctly with `transcribed_offset_ms`. The two differ by the model delay, so a phrase split whenever the reader fell behind. The pump's tick is gone; `test_the_harness_merges_two_attributed_streams` now asserts the exact five phrases | — |
| L-14 | A gap wider than 30 s is capped rather than padded | Padding minutes of silence is worse; Slice 3 closes the AudioSession instead | Slice 3 |
| L-15 | A replay reproduces segmentation exactly at any speed, but **not** a staggered join | ADR-11 anchors `epoch_ms` to the server clock when a stream opens, so only frame-derived time is speed-invariant. The harness works with this rather than against it: a scenario's `start_ms` is a wall-clock delay that is deliberately *not* divided by the speed factor, which makes the anchor identical at 1x and 10x | Never, unless the anchor stops being clock-derived |
| L-16 | A guest cannot read the transcript once the meeting ends | The review page needs a host token (L-11). Both browsers agree while the meeting is live, which is what Slice 2 claims; a guest then lands on the token gate | Slice 7 guest links (Q4) |
| L-18 | **No CI exists in the repository.** rev 4 recorded "CI added, including a contract-drift job"; there is no `.github/` directory on `main` or on any branch, and none is gitignored. PR #1 has zero check runs | Found 2026-09-06 while checking the PR. Whatever was written in Slice 0 was never committed — the same failure mode as `store.py`, minus the gitignore rule to explain it | Every claim depending on it is now local-only: `ruff`, `mypy`, `pytest`, `npm test`, `npm run build` and the OpenAPI drift check pass on a developer's machine and nowhere else. Restoring CI is Slice 0 work; it is named here rather than folded into a feature slice |
| L-17 | `frontend/node_modules/` is tracked in git (4191 files) | Pre-existing; `.gitignore` covers new files but the old entries are still indexed, so an `npm install` dirties the tree. `__pycache__` was untracked on 2026-09-06 — 38 `.pyc` files, unambiguously build output, and they re-dirtied on every test run. `node_modules` is left alone: untracking it changes how a fresh checkout is bootstrapped, which is a call to make on its own | A deliberate decision about how dependencies are vendored |

---

## 11. Changelog

| Date | Change |
|---|---|
| 2026-09-03 | Created. Q1 closed → companion mode. D-02 timeline model added. Blueprint amendments A-1…A-10 recorded. Nothing implemented. |
| 2026-09-03 | rev 2. Platform research folded into prototype scope. **Reverted in rev 3 as scope creep.** |
| 2026-09-06 | **rev 5. Slice 1 complete.** Full spine on fakes: WS gateway, `MeetingIngress` seam, ParticipantSession with the ADR-11 timeline, pure segmenter, evidence-validated intelligence, job processor with retries, and the browser UI (worklet, WS client, reconciler, join/live/review). 121 tests. Four bugs found by the tests and fixed: an `AudioSession` id mismatch breaking every segment insert; a frame pump that starved the reader; a cancelled `anext` silently killing the event stream; and silence detection comparing stream time against wall time, which fabricated segment breaks whenever audio arrived faster than real time. One test-isolation bug fixed: jobs leaked between tests, so the processor claimed a previous test's work. |
| 2026-09-05 | rev 4. Slice 0 complete and VERIFIED.** Repo initialised (uv, not pip). Migration `0001` creates all eight tables. `POST/GET /meetings`, `GET /meetings/{id}`, `/livez`. React app with an OpenAPI-generated typed client. 46 tests, ruff clean, mypy strict clean. CI added, including a contract-drift job that fails when the committed OpenAPI document does not match the code. One contract gap found and fixed during the slice: the error envelope was in the spec but absent from OpenAPI, so the generated client could not type it. |
| 2026-09-06 | rev 6a. Correction, not new work: **the CI that rev 4 claimed does not exist.** No `.github/` on `main` or any branch, not gitignored, and PR #1 reports zero check runs. Recorded as L-18. Every "passes" in rev 6 below was measured locally in this session and is not enforced anywhere. |
| 2026-09-06 | **rev 6. Slice 2 complete in software.** `tools/replay` v1 drives N streams into the real gateway over real WebSockets at a chosen speed and writes a JSON report with per-segment latency. Multi-participant runtime: roster and speaking derived from ingress events only, never from socket counts. Frontend participant panel, per-speaker attribution, cross-participant ordering. 137 tests (85 backend unit, 32 backend integration, 18 frontend unit, 2 Playwright specs — both now executed, closing L-12). **Two bugs found, both by the harness.** First: the frame pump still ticked the segmenter with audio *pushed* rather than audio *transcribed*, so a phrase split whenever the reader lagged — the ADR-11 bug half-reintroduced, and the cause of L-13, now closed. Second, in the repository rather than the code: `.gitignore`'s unanchored `audio/` also matched `backend/src/mosaique/speech/audio/`, so `store.py` had never been committed and a clean checkout could not start the app. **Not done, not claimed:** the cross-network run (A-8) and Spike A both need hardware this environment does not have. |
| 2026-09-03 | rev 3. Prototype scope restored; Technical Specification v0.1 is normative. D-01 restored. D-04 reduced to a minimal `MeetingIngress` seam (one Protocol, one enum column); speculative schema deltas withdrawn. D-05 added: Kyutai assumptions confirmed, flush trick adopted. Platform analysis moved to ADR-12 as non-normative. Q11–Q13 deferred and blocking nothing. Slice 4b removed from the prototype sequence. Still nothing implemented. |
