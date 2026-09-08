# PROJECT_STATE.md

**Project:** Mosaïque — realtime meeting intelligence, French-first
**Last updated:** 2026-09-08 (rev 10 — Spike B1 harness written, not run)
**Updated by:** Spike B1 build session
**Current slice:** **None in progress. Slice 3 is merged (PR #2) and VERIFIED.**
Next is Slice 4 — real Kyutai, and ADR-13 puts **Spike B1** in front of it.
B1's harness now exists (`backend/tools/spike_b1/`) and **has never been run**:
it needs Apple silicon and this environment has none. Four items are open and
none of them is code: Spike B1, the cross-network run (A-8), Spike A, and the
GPU half of A-9. All four need hardware this environment does not have.
**Maturity level (skill §41):** Level 1 — functional prototype, multi-participant,
fake models, failure behavior covered

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

**Slices 0 through 3 are VERIFIED and merged to `main` — PR #1 (Slice 2) and
PR #2 (Slice 3), both on 2026-09-07. The browser specs were re-run locally by
the maintainer against a real browser and passed (L-12 closed). Slice 3's exit
gate is met: every row of the tech spec §14.1 failure matrix that does not need
a real model has a named passing test, and the accelerated hour passes.**

**Four things are NOT done and are not claimed, none of them code:** Spike B1
(its harness is written and has never been run), a cross-network run between two
physical machines (A-8), Spike A, and the GPU half of A-9. **Everything from
Slice 4 onward is still `SPECIFIED`, and no real audio has ever been transcribed
by this system.**

---

## 1. Snapshot

| Field | Value |
|---|---|
| Repository | `main` through PR #2 (Slice 3). Work branch `claude/awesome-ritchie-iu6uut`, restarted from `main` after each merge |
| Runnable | yes — `docker compose up`, or uv + local PostgreSQL |
| Deployed | no |
| Real audio ever transcribed by this system | **no — every model in the path is a fake** |
| Tests passing | **218**: 141 backend unit, 48 backend integration and realtime (real PostgreSQL), 27 frontend unit, 2 Playwright browser specs. Plus one opt-in accelerated hour behind `-m slow`. The 189 backend tests were run in this session on 2026-09-08; the 29 frontend and browser tests were not re-run and are carried forward from rev 9 |
| Lint / types | ruff clean; mypy strict clean on 75 source files (the replay harness and Spike B1's two pure modules included); `tsc --noEmit` clean, carried forward from rev 9 |
| Known gap | A-8 unvalidated: every run so far is loopback on one machine. Spike A not run. **No CI runs on this repository** — see L-18. |
| Next action | **Spike B1** — run `backend/tools/spike_b1/probe.py` on Apple silicon and fill in `docs/spikes/B1-findings.md`. It is written and unrun. Slice 4 starts after it |
| Next gate | Slice 4 exit: a 3-minute French fixture replayed at real time against the real model, with WER and p95 first-word latency measured and written into §8 |

---

## 2. Locked decisions

| ID | Decision | Date | Recorded in |
|---|---|---|---|
| D-01 | Prototype ingress is browser capture over WebSocket. No LiveKit, no SFU, no platform integration. | 2026-09-03 | Blueprint §2.1 |
| D-04 | Minimal `MeetingIngress` seam so the ingress is replaceable later. One implementation, one enum column. | 2026-09-03 | Blueprint §2.1a |
| D-05 | Kyutai spec assumptions confirmed; flush trick adopted for segment-close latency. | 2026-09-03 | Blueprint §2.1b |
| ADR-12 | Media-plane options for later. **Non-normative — governs nothing.** | 2026-09-03 | `mosaique-future-media-plane-options.md` |
| ADR-13 | Model fixed, runtime is a config axis: `fake` / `mlx` / `moshi_server`. MLX is the development runtime; `moshi-server` stays the deployment one. Splits Spike B into B1 (MLX, blocks Slice 4) and B2 (CUDA, blocks Slice 6). | 2026-09-07 | `docs/ADR-013-mlx-development-runtime.md` |
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
| Reliability: 10 s disconnect without duplication | pass | **VERIFIED** | `test_a_disconnect_mid_meeting_costs_a_pause_not_a_segment` and `test_replayed_frames_do_not_duplicate_the_transcript` — the harness drops the socket mid-phrase and the transcript is unchanged |
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
| `realtime/gateway/` WS endpoint | §7 | **VERIFIED** | `test_websocket_refuses_audio_before_a_valid_hello`, flow tests, `tests/realtime/test_transport_health.py` (ping, stale close) |
| `realtime/protocol/` schemas + frame codec | §7.1–7.2 | **VERIFIED** | `tests/unit/test_frame_codec.py` (7) |
| `realtime/sessions/` ParticipantSession | §7.4 | **VERIFIED** | `tests/unit/test_participant_session.py` (11) |
| `realtime/sessions/` MeetingRuntime roster + speaking | Slice 2 | **VERIFIED** | `test_the_runtime_announces_the_roster_and_who_is_speaking` |
| `realtime/sessions/` reconnect grace + resume | §7.4 | **VERIFIED** | `tests/realtime/test_reconnect.py` (4) |
| `realtime/sessions/` idle close + pause | D-02, R-1 | **VERIFIED** | `tests/realtime/test_idle_and_pause.py` (2) |
| `realtime/sessions/` overload policy + gaps | §8.3, §8.4 | **VERIFIED** | `tests/unit/test_overload_policy.py` (10), `tests/unit/test_stream_status.py` (5), `tests/realtime/test_gaps.py` (2) |
| `realtime/sessions/` degraded persistence | §14.1 | **VERIFIED** | `tests/realtime/test_degraded_persistence.py` (3) |
| Graceful drain on shutdown | §14.1 | **VERIFIED** | `tests/realtime/test_graceful_shutdown.py` (2) |
| `realtime/ingress/` MeetingIngress protocol | Blueprint D-04 | **VERIFIED** | `test_architecture.py` parses every downstream module for transport imports |
| `speech/interfaces/` StreamingRecognizer | §9.1 | **VERIFIED** | `test_fake_and_kyutai_adapters_satisfy_the_same_protocol` |
| `speech/adapters/fake/` | §9.1 | **VERIFIED** | drives all Slice 1 and Slice 2 flow tests |
| `speech/adapters/kyutai/` | §9.2 | SPECIFIED | — | Slice 4 |
| `transcript/segmenter.py` | §9.3 | **VERIFIED** | `tests/unit/test_segmenter.py` (12) |
| `intelligence/` LLMProvider + schema | §12 | **VERIFIED** | `tests/unit/test_output_schema.py` (7) |
| `persistence/` models, repos, migrations | §4 | **VERIFIED** | migration `0001` applies from empty; `test_all_eight_tables_exist_in_migration_one`, `test_meeting_survives_a_new_session` |
| `jobs/` processor loop | §12.1 | **VERIFIED** | `tests/integration/test_intelligence_flow.py` (7): retry, failure isolation, no duplicate outputs |
| `observability/` metrics + logging | §15 | PARTIAL | Five metrics in-process (four from R-9, plus `asr_frames_skipped` which Slice 3's overload policy is unobservable without). No Prometheus exporter until Slice 6 |
| `tools/replay/` harness | §14.3 | **VERIFIED** | `tests/integration/test_replay.py` (4). Drives the real gateway over a real WebSocket against an app-server in its own process |
| Frontend `audio/` worklet | §8.2 | **VERIFIED** | `e2e/meeting.spec.ts` streams through it from Chromium's fake device |
| Frontend `realtime/` reconciler | §7.3 | **VERIFIED** | `src/realtime/__tests__/reconciler.test.ts` (11), including cross-participant ordering |
| Frontend `realtime/` roster | Slice 2 | **VERIFIED** | `src/realtime/__tests__/roster.test.ts` (7) |
| Frontend `meeting/ParticipantPanel` | Slice 2 | **VERIFIED** | `e2e/two-participants.spec.ts` asserts both names and the speaking state |
| Frontend `realtime/` WS client | §7 | **VERIFIED** | both e2e specs. Reconnect with backoff, 15 s frame buffer, ping/pong, `stream.status`; the buffer itself is covered by `buffer.test.ts` (4) |
| Frontend `realtime/` silence watcher | §8.2 | **VERIFIED** | `silence.test.ts` (5) |
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
| `ping` / `pong` | 3 — **VERIFIED** (`tests/realtime/test_transport_health.py`). Travels both ways; see §10 L-19 |
| `participant.joined` / `participant.left` | 2 — **VERIFIED** (`test_the_runtime_announces_the_roster_and_who_is_speaking`) |
| `participant.reconnecting` | 3 — IMPLEMENTED. Broadcast when the grace starts; no test asserts a client acts on it |
| `participant.speaking` | 2 — **VERIFIED**. Carries `active`, per spec §7.2; Slice 2 shipped `speaking` and Slice 3 corrected it |
| `stream.status` | 3 — **VERIFIED** (`tests/unit/test_stream_status.py`, 5 cases) |
| `audio.pause` / `audio.resume` | 3 — **VERIFIED** (`test_pausing_is_recorded_and_a_frame_unpauses`) |
| `meeting.outputs.ready` | 5 |

### Database tables

All eight — `Organization`, `User`, `Meeting`, `Participant`, `AudioSession`, `TranscriptSegment`, `MeetingOutputs`, `Job` — **MIGRATED** in revision `0001`. Amendments A-5 (Job.meeting_id FK, MeetingOutputs has no status) and D-04 (`Meeting.source_kind`) are applied. `AudioSession.epoch_ms` is present for the D-02 timeline but unused until Slice 1.

---

## 7. Assumption register

Mirrors blueprint §5. Status here is the live one.

| # | Assumption | Risk if false | Validated by | Status |
|---|---|---|---|---|
| A-1 | Browser AEC suppresses far-end audio from another app | Prototype meetings need headphones | Spike A (informational) | UNVALIDATED, non-blocking. Needs two machines and real microphones; the join page still carries the Slice 1 headphone guidance unchanged |
| A-2 | Kyutai: 24 kHz, 80 ms, word timestamps, semantic VAD, no retraction | Audio format + segmenter change | Spike B1 | **MOSTLY CONFIRMED (D-05)** — retraction still open. `backend/tools/spike_b1/` is written and has never been run; it needs Apple silicon. Its retraction detector is unit-tested against a synthetic retraction, so a clean result will mean it looked, but the measurement itself does not exist yet |
| A-3 | `moshi-server` handles concurrent streams | Fall back to PyTorch adapter | Spike B2 | UNVALIDATED — **the main Spike B2 question**, and B1 cannot touch it: concurrency is a property of the serving runtime, not the model. Needs CUDA (ADR-13 M-4) |
| A-4 | One GPU sustains 4 real-time streams | Ceiling and cost change | Spike C (half day) | **LARGELY ANSWERED** — vendor figure ~400 real-time streams per H100; confirm on our hardware |
| A-12 | Flush trick available through the adapter | Final-segment latency reverts to model delay | Spike B1, then Slice 4 | UNVALIDATED. B1 measures the realised speed factor, which is what decides it: below ~1.5x there is nothing for `flush()` to catch up with and the answer is negative **for MLX only** |
| A-5 | 60-min transcript fits one LLM context | Chunking moves into Slice 5 | Spike D | UNVALIDATED |
| A-6 | LLM returns valid `evidence_segment_ids` | Evidence linking softens | Slice 5 | UNVALIDATED |
| A-7 | Worklet resampling is cheap on mid-range laptops | Resample server-side | Slice 1 | UNVALIDATED — the e2e runs the worklet but measures no CPU cost |
| A-8 | 12.5 frames/s per participant survives real networks | Batch or enlarge frames | Slice 2 | **UNVALIDATED — the one Slice 2 exit-gate item still open.** Every run so far is loopback on one machine. `tools/replay --base-url` against a second machine is the test; it has not been run |
| A-9 | 30 s ASR grace does not leak GPU memory | Shorten grace | Slice 3 | **PARTIAL** — `test_an_hour_of_meeting_does_not_grow_the_runtime` measures 0.0 MB of tracked growth across an accelerated hour on the *fake* recognizer. There is no GPU in the path yet, so the GPU half is still open until Slice 4 |
| A-10 | French WER is good enough to be useful | Model swap | Slice 4 | UNVALIDATED |
| A-11 | "Joining is consent" satisfies FR/EU law | Consent flow and DPA change | legal counsel | **UNVALIDATED — not an engineering question** |
| A-14 | Slice 3's thresholds hold against a recognizer whose timing is not a fixed script | Reconnect grace, idle close, overload window and gap threshold all need retuning together | Slice 4 | **UNVALIDATED.** Every one of them has only ever been exercised against `FakeRecognizer`, which emits a scripted line at a fixed delay. A real model's jitter is the thing these values exist to absorb, and none of it has been seen yet |
| A-15 | Per-participant runtime tasks do not corrupt shared state | A concurrency bug that no fast test can see | Slice 3 | **PARTIALLY VALIDATED, and it already failed once.** The persistence buffer was shared across participant pumps and dropped a broadcast segment; found by the two-stream accelerated hour, not by the unit suite. Other shared runtime state — the roster, `_stream_status`, `_file_frames` — is mutated from the same tasks and has no equivalent test |
| A-16 | MLX and CUDA runtimes produce equivalent transcripts within a stated tolerance | Every number measured on MLX has to be re-measured before it can describe production | Spike B2 | **UNVALIDATED, and cannot be validated until a CUDA machine exists.** ADR-13 M-7 asked for this to be recorded as "A-14", but A-14 was already taken by Slice 3's threshold assumption; it is A-16 here, and the ADR is the document that is wrong |
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
| Idle timeout closing AudioSession | 30 s | derived from D-02 | UNMEASURED. Exercised by `test_idle_and_pause.py` at a shortened value; the 30 s itself is still a guess |
| Segments held while the database is unreachable | 200 | guess (tech spec 14.1) | UNMEASURED. Nobody has measured how long 200 segments buys, or what a real outage lasts |
| Missing-frame run that earns a gap marker | 2 000 ms | guess (tech spec 8.3) | UNMEASURED. Below it a lost packet is padded silently; the threshold has only been exercised against fixed-size synthetic gaps |
| Concurrent streams per GPU | ~400/H100 (vendor figure) | Kyutai docs | UNCONFIRMED ON OUR HARDWARE |
| Replay realised speedup at `--speed 10` | 4.17x — 20 s of stream in 4.8 s wall | `tools/replay`, 2 streams, 2026-09-06 | MEASURED. The ceiling is the harness pacing and loopback, not the runtime |
| First-word latency p95, 1x, 2 participants | 915 ms | replay report, 2026-09-06 | MEASURED — **fake recognizer over loopback**. Dominated by the fake's 500 ms scripted model delay. Not the NFR and not a prediction of it |
| Pipeline turnaround p95 (frame out → interim text back), 1x | 962 ms | same report | MEASURED, same caveat |
| Pipeline turnaround p95 at 10x | 98 ms | same report | MEASURED. Lower because the fake's model delay is stream time, which compresses |
| Accelerated hour, 2 participants at `--speed 60` | 65.7 s wall for 3 600 s of stream — **54.8x realised** | `tests/realtime/test_long_run.py`, 2026-09-07 | MEASURED. The earlier ~3.3x figure was the harness generating its own audio, not the runtime |
| Tracked memory growth over an accelerated hour | **0.0 MB** | same run, `tracemalloc` around the whole replay | MEASURED on the **fake** recognizer. Nothing in the realtime path grows with meeting length; A-9's GPU half is still open until Slice 4 |
| Frames dropped, 2 participants at 10x | 0 of 250 per stream | `audio_sessions.frames_dropped` after a CLI replay, 2026-09-06 | MEASURED on loopback. A-8 is about real networks and is still open |
| Segment-close latency with vs. without flush trick | unknown | — | UNMEASURED |
| French WER on real meeting audio | unknown | — | UNMEASURED |
| Cross-talk misattribution rate (speakerphone) | unknown | — | UNMEASURED |

---

## 9. Test inventory

| Suite | Covers | Status |
|---|---|---|
| `tests/unit/` | state machine, config, authorization, segmenter, frame codec, participant session, output schema, **architecture boundaries**, overload policy, stream status | **103 passing** |
| `tests/integration/` | create/read/list, tenancy, durability, join, live transcript, end idempotency, job retry, failure isolation, startup recovery | **28 passing** |
| `tests/integration/test_replay.py` | two streams merged and attributed; 1x ≡ 10x; roster and speaking; report shape | **4 passing** — runs a real app-server subprocess and drives it over real WebSockets |
| `frontend src/**/*.test.ts` | transcript reconciler (11), participant roster (7), reconnect frame buffer (4), silence watcher (5) | **27 passing** (vitest) |
| `e2e/meeting.spec.ts` | full single-participant browser flow with a fake microphone | **1 passing** (L-12 closed); confirmed on the maintainer's machine 2026-09-07 |
| `e2e/two-participants.spec.ts` | two browsers, merged attributed transcript, roster, speaking indicator | **1 passing**; confirmed on the maintainer's machine 2026-09-07 |
| `tests/realtime/` | reconnect and resume (4), transport health (2), idle and pause (2), gap markers (2), degraded persistence (3), graceful shutdown (2), failure matrix through the harness (3) | **18 passing** |
| `tests/realtime/test_long_run.py` | an accelerated hour, for memory stability (A-9) | **1 passing** in ~70 s; deselected by default — `uv run pytest -m slow` |
| smoke (real model) | WER + latency on French fixture | NOT WRITTEN — Slice 4 |
| cross-network run (A-8) | two physical machines, one meeting | **NOT RUN** — needs a second machine. `tools/replay --base-url` is the harness for it |
| `tests/unit/test_spike_b1_analysis.py` | what Spike B1 concludes from a token log: retraction detection, word assembly and timing, speed verdict, `asr_version`, VAD rising edges, the report shape | **37 passing.** Covers the reasoning, not the model — `probe.py` itself is untested and untestable here |
| Spike B1 (`backend/tools/spike_b1/probe.py`) | retraction, realised speed factor, quantization and identity, event shape | **WRITTEN, NEVER RUN.** Needs Apple silicon; this environment has none. Findings template at `docs/spikes/B1-findings.md` is empty |
| Spike B2 | concurrent independent streams, GPU capacity | **NOT RUN** — needs a CUDA machine (ADR-13 M-4, M-6) |
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
| L-23 | ~~The accelerated-hour test does not pass~~ **CLOSED 2026-09-07** | It now passes in ~70 s. Getting there took four causes, three of them the harness's own: it never answered server pings; its send loop starved the reader that would have; and it built an hour of synthetic audio with a per-sample loop *after* opening the socket, so the server saw a client that connected and went silent for 30 s. The fourth was real: concurrent pumps sharing one persistence buffer could drop a segment that had already been broadcast | — |
| L-22 | `test_replayed_frames_do_not_duplicate_the_transcript` failed once in a full-suite run, and has not been reproduced | The server closed the harness's opening handshake with 1008, which means it could not find the meeting or the participant row. Two harness-driven modules share one database and each test truncates it, so a teardown overlapping a setup is the obvious suspect — but it survived four targeted re-runs and three subsequent full runs, so the mechanism is **not established**. The handshake now names itself when this happens instead of raising a bare `ConnectionClosedError` | Next time it fires. If it becomes frequent, give the harness modules separate databases rather than sharing one |
| L-19 | The spec has the server pinging (§7.4) but lists only `pong` coming back (§7.2) | Both directions are needed — a suspended tab stops sending without closing — so one message shape serves both and `ping` travels each way. Recorded rather than silently diverging | If §7.2 is ever revised, this is the paragraph to update |
| L-20 | A gap segment is a real row with empty text and its own status | The alternative was an omission, which is indistinguishable from "nobody spoke". Downstream consumers must therefore skip `status='gap'` when concatenating transcript text — the Slice 5 prompt builder is the next one that will care | Slice 5 |
| L-21 | The reconnect grace and the idle close are both 30 s and can race | A socket that drops and never returns finalizes once, whichever timer wins, because both paths remove the session before finalizing. The behaviour is correct but the coincidence is not designed — the two values are independent `[measure]` guesses that happen to match | Slice 4, when both are tuned against real audio |
| L-18 | **No CI exists in the repository.** rev 4 recorded "CI added, including a contract-drift job"; there is no `.github/` directory on `main` or on any branch, and none is gitignored. PR #1 has zero check runs | Found 2026-09-06 while checking the PR. Whatever was written in Slice 0 was never committed — the same failure mode as `store.py`, minus the gitignore rule to explain it | Every claim depending on it is now local-only: `ruff`, `mypy`, `pytest`, `npm test`, `npm run build` and the OpenAPI drift check pass on a developer's machine and nowhere else. Restoring CI is Slice 0 work; it is named here rather than folded into a feature slice |
| L-17 | `frontend/node_modules/` is tracked in git (4191 files) | Pre-existing; `.gitignore` covers new files but the old entries are still indexed, so an `npm install` dirties the tree. `__pycache__` was untracked on 2026-09-06 — 38 `.pyc` files, unambiguously build output, and they re-dirtied on every test run. `node_modules` is left alone: untracking it changes how a fresh checkout is bootstrapped, which is a call to make on its own | A deliberate decision about how dependencies are vendored |

---

## 11. Changelog

| Date | Change |
|---|---|
| 2026-09-08 | **rev 10. Spike B1's harness written; nothing measured.** `backend/tools/spike_b1/` is a PEP 723 script that runs `kyutai/stt-1b-en_fr-mlx` over a French fixture and prints four answers — retraction, realised speed factor, quantization and identity, event shape — plus `docs/spikes/B1-findings.md` as an empty template. **It has never been executed anywhere.** It cannot be: MLX needs Apple silicon. What *is* proven is everything it concludes: the token-log reasoning lives in two MLX-free modules with 37 passing tests (`tests/unit/test_spike_b1_analysis.py`), including a synthetic retraction the detector is required to catch — without that, "no retraction observed" would be indistinguishable from a detector that cannot see. Backend suite 152 -> 189, all run on 2026-09-08. Three smaller things, each recorded where it belongs: ADR-13 was accepted on 2026-09-07 but had never reached §2, so it is there now; `mlx` and `mlx_lm` joined `MODEL_MODULES` in the architecture test per ADR-13 consequence 4, before any adapter exists to need it; and ADR-13 M-7's new assumption is recorded as **A-16**, not the "A-14" the ADR asks for, because A-14 was already taken by Slice 3's threshold assumption. MLX never enters `backend/pyproject.toml` (ADR-13 consequence 5) — the spike is a standalone script with its own throwaway environment, which is also why `test_architecture.py` stays green with a model library in the repository. |
| 2026-09-03 | Created. Q1 closed → companion mode. D-02 timeline model added. Blueprint amendments A-1…A-10 recorded. Nothing implemented. |
| 2026-09-03 | rev 2. Platform research folded into prototype scope. **Reverted in rev 3 as scope creep.** |
| 2026-09-06 | **rev 5. Slice 1 complete.** Full spine on fakes: WS gateway, `MeetingIngress` seam, ParticipantSession with the ADR-11 timeline, pure segmenter, evidence-validated intelligence, job processor with retries, and the browser UI (worklet, WS client, reconciler, join/live/review). 121 tests. Four bugs found by the tests and fixed: an `AudioSession` id mismatch breaking every segment insert; a frame pump that starved the reader; a cancelled `anext` silently killing the event stream; and silence detection comparing stream time against wall time, which fabricated segment breaks whenever audio arrived faster than real time. One test-isolation bug fixed: jobs leaked between tests, so the processor claimed a previous test's work. |
| 2026-09-05 | rev 4. Slice 0 complete and VERIFIED.** Repo initialised (uv, not pip). Migration `0001` creates all eight tables. `POST/GET /meetings`, `GET /meetings/{id}`, `/livez`. React app with an OpenAPI-generated typed client. 46 tests, ruff clean, mypy strict clean. CI added, including a contract-drift job that fails when the committed OpenAPI document does not match the code. One contract gap found and fixed during the slice: the error envelope was in the spec but absent from OpenAPI, so the generated client could not type it. |
| 2026-09-07 | **rev 9. Slice 3 merged as PR #2.** Exit gate met: every §14.1 failure-matrix row that needs no real model has a named passing test, and the accelerated hour passes at 54.8x realised with 0.0 MB of tracked growth. 181 tests. Four bugs were found getting the hour to pass, and the split is the point: three were the harness's own — it never answered server pings, its send loop starved the reader that would have, and it generated an hour of synthetic audio *after* opening the socket, so the server saw a client that connected and went silent for 30 s. The fourth was real and would have shipped silently: concurrent pumps sharing one persistence buffer could drop a segment that had already been broadcast, with nothing logged as failed. Its regression test was checked against the original code and fails there with the same symptom. Still open, none of it code: A-8, Spike A, and the GPU half of A-9. |
| 2026-09-07 | **rev 8. Slice 3 — failure behavior.** Reconnect grace with sequence resume; ping/pong and stale-socket detection; `audio.pause`/`audio.resume` and the D-02 idle close; the §8.4 overload policy with gap segments and `stream.status`; segment buffering when the database is unreachable; graceful drain on shutdown; client-side reconnect with a bounded buffer, and the silent-microphone warning. The harness gained the fault injection §14.3 asks for. Three bugs found while building it: `participant.speaking` shipped in Slice 2 with the wrong field name for the spec; a participant whose stream was idle-closed and then disconnected was never announced as left; and the harness itself never answered server pings, which killed the first accelerated-hour run. |
| 2026-09-07 | **rev 7.** Slice 2 merged to `main` as PR #1. Both Playwright specs re-run locally by the maintainer against a real browser and passed, which is what moves Slice 2 from "verified in this sandbox" to verified. `__pycache__` untracked (L-17 narrowed to `node_modules` alone). §12 "Where to pick up" added so a cold session can start without re-deriving the environment or the Slice 3 scope. Slice 3 begun. |
| 2026-09-06 | rev 6a. Correction, not new work: **the CI that rev 4 claimed does not exist.** No `.github/` on `main` or any branch, not gitignored, and PR #1 reports zero check runs. Recorded as L-18. Every "passes" in rev 6 below was measured locally in this session and is not enforced anywhere. |
| 2026-09-06 | **rev 6. Slice 2 complete in software.** `tools/replay` v1 drives N streams into the real gateway over real WebSockets at a chosen speed and writes a JSON report with per-segment latency. Multi-participant runtime: roster and speaking derived from ingress events only, never from socket counts. Frontend participant panel, per-speaker attribution, cross-participant ordering. 137 tests (85 backend unit, 32 backend integration, 18 frontend unit, 2 Playwright specs — both now executed, closing L-12). **Two bugs found, both by the harness.** First: the frame pump still ticked the segmenter with audio *pushed* rather than audio *transcribed*, so a phrase split whenever the reader lagged — the ADR-11 bug half-reintroduced, and the cause of L-13, now closed. Second, in the repository rather than the code: `.gitignore`'s unanchored `audio/` also matched `backend/src/mosaique/speech/audio/`, so `store.py` had never been committed and a clean checkout could not start the app. **Not done, not claimed:** the cross-network run (A-8) and Spike A both need hardware this environment does not have. |
| 2026-09-03 | rev 3. Prototype scope restored; Technical Specification v0.1 is normative. D-01 restored. D-04 reduced to a minimal `MeetingIngress` seam (one Protocol, one enum column); speculative schema deltas withdrawn. D-05 added: Kyutai assumptions confirmed, flush trick adopted. Platform analysis moved to ADR-12 as non-normative. Q11–Q13 deferred and blocking nothing. Slice 4b removed from the prototype sequence. Still nothing implemented. |

---

## 12. Where to pick up

Written so a cold session can start without re-deriving anything. This section
describes **intent**, unlike the rest of this file; when it disagrees with the
tables above, the tables are right.

### Environment, from a clean container

```bash
# PostgreSQL is installed but not running in a fresh container
pg_ctlcluster 16 main start
su postgres -c "psql -c \"CREATE ROLE mosaique LOGIN PASSWORD 'mosaique' SUPERUSER;\""
su postgres -c "createdb -O mosaique mosaique_test"
su postgres -c "createdb -O mosaique mosaique"

cd backend && uv venv && uv pip install -e ".[dev]"
MOSAIQUE_TEST_DATABASE_URL="postgresql+asyncpg://mosaique:mosaique@localhost:5432/mosaique_test" uv run pytest -q

cd ../frontend && npm install && npm test
```

Playwright's own browser download is blocked in the web sandbox, but a Chromium
is already on disk. Both browser specs pass with:

```bash
export MOSAIQUE_CHROMIUM_PATH=/opt/pw-browsers/chromium
export MOSAIQUE_HOST_TOKEN="$(cd ../backend && uv run python -m mosaique.app.seed | tail -1)"
npx playwright test          # needs backend on :8000 and vite on :5173
```

### Slice 3 — delivered and merged (PR #2)

Every item, with the test that proves it. All of `tests/realtime/` is new.

| # | Item | Spec | Evidence |
|---|---|---|---|
| 1 | `ping`/`pong`, stale socket after 30 s | §7.4 | `test_transport_health.py` (2) |
| 2 | 30 s reconnect grace, resume in place, buffered frames accepted | §7.4, X-13 | `test_reconnect.py` (4) |
| 3 | Beyond the grace: finalize, new AudioSession on reconnect | §7.4 | same file |
| 4 | `SESSION_REPLACED` closes the first socket | §7.4 | same file |
| 5 | AudioSession closed after 30 s idle, fresh anchor on resume | D-02 | `test_idle_and_pause.py` (3) |
| 6 | `audio.pause` / `audio.resume` honoured | R-1 | same file |
| 7 | Queue policy: `delayed` with `lag_ms`, skip from the ASR queue only, gap segment, `unavailable` past 15 s | §8.4 | `test_overload_policy.py` (10), `test_stream_status.py` (5) |
| 8 | `stream.status` and the five states | §7.2 | `test_stream_status.py` |
| 9 | `seq` gap > 2 s inserts a gap marker | §8.3 | `test_gaps.py` (2) |
| 10 | DB unavailable: hold, then `unavailable`, audio continues | §14.1 | `test_degraded_persistence.py` (4) |
| 11 | Graceful drain: stop joins, finalize, close 1012 | §14.1 | `test_graceful_shutdown.py` (2) |
| 12 | Silent microphone → "no audio detected" | §8.2 | `silence.test.ts` (5) |
| 13 | Fault injection in the harness: disconnect at t, duplicate frames at t | §14.3 | `test_failure_matrix.py` (3) |
| 14 | 60-minute accelerated run | §14.2 | `test_long_run.py`, behind `-m slow` |

**Not covered, and worth knowing before Slice 4:**

* The `stream.status` *UI* is wired but no browser test asserts what a
  participant sees in each of the five states. The mapping is tested; the
  rendering is not.
* `participant.reconnecting` is broadcast but nothing asserts a client acts
  on it.
* Sustained overload is proven at the policy level, not by saturating a real
  queue through the gateway.
* Concurrency has thin coverage in the fast suite — see A-15. The one bug found
  there was found by the hour-long test, not by the 152 that run in a minute.

### Slice 4 — what comes next

Read `docs/IMPLEMENTATION_PLAN.md` Slice 4 and tech spec §9.2 before starting.
In short: apply Spike B's findings to §8.1 and §9.3 *before* writing the
adapter, build the `asr-runtime` container, put Kyutai behind
`StreamingRecognizer` with bounded reconnect backoff and `health()`, add the
full latency decomposition, and tune the segmentation thresholds against real
French audio with the replay harness.

**It is blocked on Q2, Spike B and Spike C** — none of which is code, and all
of which are recorded as open in §3 and in the plan's spike table. Do not start
the adapter before Spike B: it is the only thing that can still break the §9.2
decision, and if `moshi-server` cannot serve concurrent independent streams the
adapter goes in-process instead.

**This is the slice that can invalidate earlier work.** Every `[measure]` value
in §8 has so far been tuned against a recognizer that emits a fixed script at a
fixed delay (A-14). If French WER on real meeting audio turns out unusable,
ADR-03 reopens — §10 calls that the largest technical risk left in the
prototype.

### Traps

Four mistakes this project has actually made, each more than once in spirit,
are written up in `CLAUDE.md` under **Known traps**: stream time versus wall
time, shared runtime state across participant tasks, unanchored globs in
`.gitignore`, and holding a socket open while doing slow work.

Read them before touching the realtime path. The regression test for the first
is `test_ten_times_speed_produces_the_same_transcript_as_real_time`; for the
second, `test_two_pumps_persisting_at_once_lose_nothing`. Keep both passing.
