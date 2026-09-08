# PROJECT_STATE.md

**Project:** Mosaïque — realtime meeting intelligence, French-first
**Last updated:** 2026-09-08 (rev 13 — Slice 5 built; its gate needs an API key)
**Updated by:** Slice 5 implementation session
**Current slice:** **Slice 5 — real meeting intelligence. Code complete; gate not met.**
The OpenAI provider, the FR-11 audio route and the evidence-linked review page
are merged and tested. **No real LLM call has ever been made from this
codebase** (L-31): every test runs on `FakeLLMProvider` or a fake transport, and
the gate's "ten real meetings" and A-6's rejection rate both need a key.
**Slice 4 remains MET** and L-28 is deferred by decision, not by oversight —
see §10.

**Previously:** **Slice 4 — real Kyutai. Exit gate MET.**
116.36 s of French went microphone-format → gateway → runtime → adapter → real
MLX Kyutai → transcript on 2026-09-08, at 1x, on Aymen's Apple silicon:
**1.43% WER**, p95 first-word latency **1 934 ms**, 30 segments all persisted,
`asr_version` written by the app-server. Evidence:
`docs/slice4-last-test-report.json`.
**One defect is open and it is code: L-28**, the sentence-final word orphaned
into its own segment, 8 times in 30 — found in that report, invisible to its
WER, and untouched here because this pass was documentation. Decide it before
Slice 5, which consumes segments.
Still open and all hardware: the cross-network run (A-8), Spike A, the GPU half
of A-9, and Spike B2 — which also owns `moshi_server`, `EndOfTurnEvent` and A-16.
**Maturity level (skill §41):** Level 2 — functional prototype, multi-participant,
**real model on one runtime**, failure behavior covered, single-stream only

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

**Kyutai has now transcribed real French through this application**, once, at
1x, on Apple silicon — the full path, not the standalone probe. Slice 4's exit
gate is met and Slice 5 has not started.

**What is NOT done and is not claimed.** One item is code: **L-28**, the
orphaned sentence-final word, found by the same run that closed the gate and
left unfixed here on purpose. The rest is hardware: a cross-network run between
two physical machines (A-8), Spike A, the GPU half of A-9, and Spike B2 — and
Spike B2 is larger than it looks, because `moshi_server`, `EndOfTurnEvent`, the
§9.3 end-of-turn threshold and A-16 all wait behind it. Also unclaimed: anything
about **two real streams at once**, which MLX cannot do at all (L-26).

---

## 1. Snapshot

| Field | Value |
|---|---|
| Repository | `main` through PR #7 (Slice 4 documentation). Work branch `claude/awesome-ritchie-iu6uut`, restarted from `main` after each merge |
| Runnable | yes — `docker compose up`, or uv + local PostgreSQL |
| Deployed | no |
| Real audio ever transcribed by this system | **yes, once, end to end.** 116.36 s of French through the running app-server against real MLX Kyutai on Apple silicon, 2026-09-08 — `docs/slice4-last-test-report.json`. 1.43% WER, 30 segments, all persisted, meeting `COMPLETED`. One speaker, one stream, one machine, and never in this environment (L-27) |
| Tests passing | **366**: 258 backend unit, 57 backend integration and realtime (real PostgreSQL), 49 frontend unit, 2 Playwright browser specs. Plus one opt-in accelerated hour behind `-m slow`. Backend re-run in this session — `315 passed, 1 deselected in 94.81s`; frontend `49 passed`; `npm run build` clean. The 2 Playwright specs are carried forward from rev 9 and were **not** re-run against the new review page (L-32). **None of these executes a model or a provider**: the ASR evidence is a report (L-27) and the LLM has never been called (L-31) |
| Lint / types | ruff clean; ruff format clean; mypy strict clean on 88 source files; `tsc --noEmit` clean; `openapi.json` regenerated with no drift |
| Known gap | A-8 unvalidated: every run so far is loopback on one machine. Spike A not run. A-3, A-16 and `moshi_server` all still need a CUDA host. **No CI runs on this repository** — see L-18, which now also means the one run that proves Slice 4 is reproducible only by hand, on hardware. |
| Next action | **Run ten real meetings through the OpenAI provider** with `MOSAIQUE_LLM_PROVIDER=openai` and a key. It closes Slice 5's gate, answers A-6, and is the first real call this codebase will have made. The exact commands are in §12 |
| Next gate | **Slice 5 exit:** ten real meetings processed; schema-rejection rate measured (A-6); FR-11 navigation verified end to end; LLM-outage isolation confirmed. Of those four, **the outage test passes now** (`test_a_failing_provider_leaves_transcript_and_meeting_untouched`) and **FR-11 passes against stored audio** (`tests/integration/test_audio_playback.py`). The two that need a key are the ten meetings and the rejection rate |

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
| Q2 | GPU location, inference host, EU data residency | product | Slice 4, Slice 5 | **LLM provider: OpenAI `gpt-4o-mini`** (Aymen, 2026-09-08 — chosen on available credit, explicitly not on residency) | **PARTIALLY ANSWERED, and only the half that unblocks code.** Slice 5 now has a provider and is unblocked. **The residency half is untouched**: OpenAI is a US processor, and a French-SMB product handling meeting audio will have to answer that before a pilot (A-11 is the same conversation). `llm_base_url` is settable so an EU-resident or self-hosted OpenAI-compatible endpoint is a config change, not a new adapter — that is mitigation, not an answer |
| Q3 | Raw audio retention and consent | product | Slice 5, Slice 7 | store, 30 days | **OPEN, and now load-bearing.** Slice 5 built `GET /meetings/{id}/audio/{session_id}` on the standing default (Aymen, 2026-09-08), so stored audio is now *served*, not merely written. Nothing deletes anything yet; the retention job is still Slice 7 |
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
| FR-03 | Realtime transcription | Slice 1 (fake) / Slice 4 (real) | **VERIFIED, fake and real** | `test_speaking_produces_live_interim_then_final_segments`; real model in `docs/slice4-last-test-report.json` (1.43% WER) | The real half is a report no test re-runs (L-27) |
| FR-04 | Interim and final events | Slice 1 | **VERIFIED** | `tests/unit/test_segmenter.py` (12), `reconciler.test.ts` (11), flow test asserts both statuses |
| FR-05 | Speaker association | Slice 2 | **VERIFIED (endpoint capture)** | `test_the_harness_merges_two_attributed_streams`, `e2e/two-participants.spec.ts` | Two streams, each segment under its own speaker, in both browsers. Attribution when one microphone hears another person is Spike A and is **not** covered (L-2) |
| FR-06 | Finalized transcript | Slice 1 | **VERIFIED** | `test_only_final_segments_reach_the_database`, `test_startup_recovery_completes_a_stranded_finalizing_meeting` |
| FR-07 | Meeting summary | Slice 1 (fake) / Slice 5 (real) | **VERIFIED (fake only)** | `test_processor_produces_evidence_linked_outputs` | The real provider is merged and unit-tested but has never been called (L-31) |
| FR-08 | Action item extraction | Slice 1 (fake) / Slice 5 (real) | **VERIFIED (fake only)** | same test; evidence ids checked against real segments | Same caveat as FR-07 (L-31) |
| FR-09 | Decision extraction | Slice 1 (fake) / Slice 5 (real) | **VERIFIED (fake only)** | same test | Same caveat as FR-07 (L-31) |
| FR-10 | Transcript review and search | read: Slice 1, search: Slice 6 | **read VERIFIED** | `GET /transcript` covered, ordered across participants by `start_ms`; search is Slice 6 |
| FR-11 | Timestamp navigation | Slice 5 | **VERIFIED (server side); browser side untested** | `tests/integration/test_audio_playback.py` (7), `playback.test.ts` (11), `evidence.test.ts` (11) | Range route, offset arithmetic and citation resolution all covered. Nobody has clicked a citation in a real browser — L-32 |

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
| `speech/adapters/kyutai/` identity, pieces, backoff, session | §9.1, §9.2 | **VERIFIED** | `tests/unit/test_kyutai_adapter.py` (34) — identity and `asr_version`, streaming word assembly, bounded reconnect, health, lag, the ASR liveness check, and the moshi-server message translation against a fake transport |
| `speech/adapters/kyutai/mlx_runtime.py` | ADR-13 | **VERIFIED, by report only** | `docs/slice4-last-test-report.json` — 116 s of real French at 1x, 2026-09-08. Verified by a run, not by a test: needs Apple silicon, so neither this environment nor CI can execute it (L-27). One stream at a time by design (L-26) |
| `asr_runtime/moshi_ws.py` | §9.2 | **IMPLEMENTED** | Needs a CUDA host running `moshi-server`. The protocol logic it carries is tested; the socket and msgpack framing are not |
| `asr_runtime/factory.py` runtime selection | ADR-13 | **VERIFIED** | `tests/unit/test_asr_runtime_selection.py` (5): default is fake, unknown runtime refused, `moshi_server` without a URL fails at startup |
| `observability/latency.py` decomposition | Slice 4 | **VERIFIED** | `tests/unit/test_latency_decomposition.py` (7): per-hop attribution, the frame a word belongs to, the client-clock hop kept out of the total, bounded memory |
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
| A-2 | Kyutai: 24 kHz, 80 ms, word timestamps, semantic VAD, no retraction | Audio format + segmenter change | Spike B1 | **CLOSED 2026-09-08, partly against itself.** 24 kHz/80 ms confirmed; word timestamps derived not emitted; **no retraction** in 825 steps (X-14 stands for MLX — append-only by construction on this API, not proven of the model); and **the semantic VAD is absent on the `-mlx` weights**, which is the half of the assumption that was wrong and the reason §9.3 grew a punctuation rule |
| A-3 | `moshi-server` handles concurrent streams | Fall back to PyTorch adapter | Spike B2 | UNVALIDATED — **the main Spike B2 question**, and B1 cannot touch it: concurrency is a property of the serving runtime, not the model. Needs CUDA (ADR-13 M-4) |
| A-4 | One GPU sustains 4 real-time streams | Ceiling and cost change | Spike C (half day) | **LARGELY ANSWERED** — vendor figure ~400 real-time streams per H100; confirm on our hardware |
| A-12 | Flush trick available through the adapter | Final-segment latency reverts to model delay | Spike B1 | **ANSWERED NEGATIVELY for MLX, 2026-09-08.** 1.24x realised, below the 1.5x it needs. `MlxBackend.flush()` pushes silence and waits rather than accelerating. Unchanged by the 116 s run, which realised 0.99x at a 1x request — that measures keeping up, not headroom, and cannot exceed B1's maximum. Still open for `moshi_server`, which has the `Marker` primitive but no hardware to run on |
| A-5 | 60-min transcript fits one LLM context | Chunking moves into Slice 5 | Spike D | **ANSWERED AFFIRMATIVELY 2026-09-08, by arithmetic.** An hour of 4-person French estimates at ~37k tokens against `gpt-4o-mini`'s 128k window — `tests/unit/test_prompt_budget.py`, which tiles the real Slice 4 fixture rather than inventing one. **Chunk-and-merge was therefore not built.** Tokens are estimated from characters at a deliberately pessimistic 3 chars/token, not counted with the vendor's tokenizer; the margin is ~3x, so the estimate does not need to be tight to be decisive |
| A-6 | LLM returns valid `evidence_segment_ids` | Evidence linking softens | Slice 5 | **UNVALIDATED — needs a key.** Two defences are built and tested: OpenAI strict structured outputs constrain the *shape* during decoding, and `validate_outputs` rejects ids matching no real segment. Neither has met a real model. The rejection rate the gate asks for is a count over ten real meetings and cannot be simulated — `FakeLLMProvider` cites real ids by construction, so it can only ever pass |
| A-7 | Worklet resampling is cheap on mid-range laptops | Resample server-side | Slice 1 | UNVALIDATED — the e2e runs the worklet but measures no CPU cost |
| A-8 | 12.5 frames/s per participant survives real networks | Batch or enlarge frames | Slice 2 | **UNVALIDATED — the one Slice 2 exit-gate item still open.** Every run so far is loopback on one machine. `tools/replay --base-url` against a second machine is the test; it has not been run |
| A-9 | 30 s ASR grace does not leak GPU memory | Shorten grace | Slice 3 | **STILL PARTIAL.** `test_an_hour_of_meeting_does_not_grow_the_runtime` measures 0.0 MB of tracked growth across an accelerated hour on the *fake*. The 2026-09-08 MLX run put a real model in the path but ran 116 s and never exercised the grace window, so it says nothing about this. Needs a long real-model run, or Spike B2 |
| A-10 | French WER is good enough to be useful | Model swap | Slice 4 smoke test | **ANSWERED AFFIRMATIVELY 2026-09-08 — 1.43% WER** on 116 s of French through the app-server against a hand-written reference (`docs/slice4-last-test-report.json`). No model swap needed. Scope of the answer: one speaker, one prepared monologue, clean audio, no cross-talk and no second participant — the easiest case this product will ever see, so it is a ceiling rather than an expectation |
| A-11 | "Joining is consent" satisfies FR/EU law | Consent flow and DPA change | legal counsel | **UNVALIDATED — not an engineering question** |
| A-14 | Slice 3's thresholds hold against a recognizer whose timing is not a fixed script | Reconnect grace, idle close, overload window and gap threshold all need retuning together | Slice 4 | **PARTIALLY ANSWERED, and one threshold has already failed.** The 116 s run exercised real jitter for the first time: nothing dropped, nothing overloaded, no gap marker, `COMPLETED`. But the 1 200 ms silence threshold **did** fail against real emission timing — it closed 8 segments on silence that is not in the audio (L-28). Reconnect grace, idle close and the overload window were never provoked in 116 s and remain untested against a real model |
| A-15 | Per-participant runtime tasks do not corrupt shared state | A concurrency bug that no fast test can see | Slice 3 | **PARTIALLY VALIDATED, and it already failed once.** The persistence buffer was shared across participant pumps and dropped a broadcast segment; found by the two-stream accelerated hour, not by the unit suite. Other shared runtime state — the roster, `_stream_status`, `_file_frames` — is mutated from the same tasks and has no equivalent test |
| A-16 | MLX and CUDA runtimes produce equivalent transcripts within a stated tolerance | Every number measured on MLX has to be re-measured before it can describe production | Spike B2 | **UNVALIDATED, and cannot be validated until a CUDA machine exists.** ADR-13 M-7 asked for this to be recorded as "A-14", but A-14 was already taken by Slice 3's threshold assumption; it is A-16 here, and the ADR is the document that is wrong |
| A-13 | A participant's place on the meeting timeline may be anchored to the server clock at connect | A replay cannot reproduce a staggered join; joins would need to be frame-derived too | Slice 2 | **CONFIRMED as a property, not a guess** — see L-15. Segmentation is frame-derived and speed-invariant; the join anchor is not |

---

## 8. Measured values ledger

Every `[measure]` placeholder in the technical specification. A value here means it was measured, on a date, by something named.

| Parameter | Current value | Source | Status |
|---|---|---|---|
| First-word latency p95 target | 2.0 s (target) — **realised 1 934 ms** | measured 2026-09-08 by Aymen on Apple silicon, `docs/slice4-last-test-report.json` | **MEASURED, and inside the target.** 116.36 s of French, one participant, real MLX Kyutai at 1x through the app-server. p50 968 ms. The target row keeps its 2.0 s guess: one speaker on one machine at one concurrency is not the NFR, and the margin is 66 ms |
| Final-segment latency p95 target | 3.5 s | guess (blueprint X-4) | **STILL AWAITING MEASUREMENT.** The 2026-09-08 run reports *pipeline* latency (frame in → text broadcast), p95 1 994.7 ms, which is a different quantity: it does not include the wait for the segment to close. Do not read one as the other. With no flush trick on MLX (A-12), close latency still starts at the 500 ms model delay |
| Reconnect grace | 30 s | guess | UNMEASURED |
| ASR event timeout | 5 s | guess | UNMEASURED, and **re-specified**. Taken literally ("no event for 5 s") it fires on any pause, because most MLX steps emit nothing — 663 of B1's 825. It is now a liveness check on frames *processed*, which is the question actually being asked. `test_a_recognizer_that_stops_consuming_is_reported_not_hidden` |
| End-of-turn probability threshold | 0.5 | guess | **UNMEASURABLE ON MLX, unchanged.** The `-mlx` weights carry no VAD heads, so no `EndOfTurnEvent` is ever produced and the threshold is dead code on the development runtime. It becomes measurable on `moshi_server`, whose `Step` messages carry a VAD signal — Spike B2 |
| Silence threshold for segment close | **1 200 ms** (was 700 ms) | measured 2026-09-08 by Aymen on Apple M1, `docs/spikes/B1-findings.md` | **MEASURED, THINLY.** Raised because 700 ms split a phrase six times in 64 s of French. The speaker's largest mid-phrase gap is 1 120 ms and their shortest real sentence break is 880 ms, so the distributions overlap and **no silence threshold separates them** — which is why the punctuation rule below exists. One speaker, one 64 s recording; a second fixture can move it. Pinned by `test_segmentation_against_real_audio.py` |
| Segment duration cap | 15 s | guess | UNMEASURED, unchanged. Longest natural segment observed was 12.7 s, so nothing in B1 exercised the cap. `test_no_segment_reaches_the_duration_cap` fails the day a fixture does |
| Sentence-final punctuation closes a segment | **new rule, on** | measured 2026-09-08 by Aymen on Apple M1, `docs/spikes/B1-findings.md` | **MEASURED, THINLY.** All 3 mid-transcript `.` marks landed on real boundaries with no false positive; commas were checked separately and are followed by 0-640 ms gaps, mid-phrase. Added because §9.3's primary rule (end-of-turn) does not exist on MLX. Risk not ruled out by one fixture: `M.`, `etc.` (L-24) |
| Finalize drain deadline | 20 s | guess | UNMEASURED |
| Outputs ready after end | 90 s | guess | UNMEASURED |
| Queue depth: normal / lagging / full | 25 / 62 frames | guess | UNMEASURED |
| Sustained-overload stream failure | 15 s | guess | UNMEASURED |
| Idle timeout closing AudioSession | 30 s | derived from D-02 | UNMEASURED. Exercised by `test_idle_and_pause.py` at a shortened value; the 30 s itself is still a guess |
| Segments held while the database is unreachable | 200 | guess (tech spec 14.1) | UNMEASURED. Nobody has measured how long 200 segments buys, or what a real outage lasts |
| Missing-frame run that earns a gap marker | 2 000 ms | guess (tech spec 8.3) | UNMEASURED. Below it a lost packet is padded silently; the threshold has only been exercised against fixed-size synthetic gaps |
| MLX realised speed factor | **1.24x** (1.29x excluding first-call compilation) | measured 2026-09-08 by Aymen on Apple M1, `docs/spikes/B1-findings.md` | MEASURED on Apple M1/9 GB under memory pressure. p50 59.4 ms per 80 ms step, p95 75.2 ms, 23 of 825 steps over budget. One sample, not re-run |
| MLX model load, cold | **284 s** | same run | MEASURED. Why the app-server preloads the weights at startup instead of inside the first meeting |
| Kyutai model delay | **500 ms** | read from `config.stt_config.audio_delay_seconds` | **CONFIRMED, not assumed.** Was a model-card figure; now read from the build |
| Silence prefix the build expects | **0 ms** | read from `config.stt_config.audio_silence_prefix_seconds` | CONFIRMED. No timestamp shift is needed |
| `Meeting.asr_version` on MLX | **`kyutai/stt-1b-en_fr@mlx-bf16`** | measured 2026-09-08 by Aymen on Apple M1, `docs/spikes/B1-findings.md` | MEASURED. **bf16, not the `q4` ADR-13 used as its example** — the `-mlx` repo ships `model.safetensors` |
| Concurrent streams per GPU | ~400/H100 (vendor figure) | Kyutai docs | UNCONFIRMED ON OUR HARDWARE |
| Replay realised speedup at `--speed 10` | 4.17x — 20 s of stream in 4.8 s wall | `tools/replay`, 2 streams, 2026-09-06 | MEASURED. The ceiling is the harness pacing and loopback, not the runtime |
| First-word latency p95, 1x, 2 participants | 915 ms | replay report, 2026-09-06 | MEASURED — **fake recognizer over loopback**. Dominated by the fake's 500 ms scripted model delay. Not the NFR and not a prediction of it |
| Pipeline turnaround p95 (frame out → interim text back), 1x | 962 ms | same report | MEASURED, same caveat |
| Pipeline turnaround p95 at 10x | 98 ms | same report | MEASURED. Lower because the fake's model delay is stream time, which compresses |
| Accelerated hour, 2 participants at `--speed 60` | 65.7 s wall for 3 600 s of stream — **54.8x realised** | `tests/realtime/test_long_run.py`, 2026-09-07 | MEASURED. The earlier ~3.3x figure was the harness generating its own audio, not the runtime |
| Tracked memory growth over an accelerated hour | **0.0 MB** | same run, `tracemalloc` around the whole replay | MEASURED on the **fake** recognizer. Nothing in the realtime path grows with meeting length; A-9's GPU half is still open until Slice 4 |
| Frames dropped, 2 participants at 10x | 0 of 250 per stream | `audio_sessions.frames_dropped` after a CLI replay, 2026-09-06 | MEASURED on loopback. A-8 is about real networks and is still open |
| Segment-close latency with vs. without flush trick | **no flush trick on MLX** | measured 2026-09-08 by Aymen on Apple M1, `docs/spikes/B1-findings.md` | **A-12 ANSWERED NEGATIVELY for MLX.** D-05 assumes several times real time; MLX realised **1.24x**, so there is nothing to catch up with and close latency reverts to the ~500 ms model delay. `moshi_server` has the `Marker` primitive for it, unverified |
| French WER on real meeting audio | **1.43%** | measured 2026-09-08 by Aymen on Apple silicon, `docs/slice4-last-test-report.json`, against a hand-written golden transcript | **MEASURED. A-10 answered.** 349 reference words, 347 hypothesis, edit distance 5. The five edits are `sept heures` → `7 heures`, `et demie` → `et demi`, punctuation, and a truncated final phrase — normalisation and formatting, not misheard speech. One speaker, one 116 s monologue, clean audio, no cross-talk: this is the ceiling, not the operating point |
| Gateway → broadcast p95, real model at 1x | **1 343.46 ms** | measured 2026-09-08 by Aymen on Apple silicon, `docs/slice4-last-test-report.json`, `latency_decomposition` | MEASURED, one stream. Decomposes as gateway → dequeue 0.15 ms, dequeue → first ASR event **1 343.27 ms**, first event → broadcast 0.14 ms. Maximum 2 033.81 ms. **The model is essentially the whole latency budget**; the transport either side of it is noise |
| `capture` → `gateway_recv` | **INVALID — p95 reads ≈ 3.2×10⁹ ms** | same run | **BROKEN METRIC, not a broken pipeline** (L-29). The browser stamps `capture_ms` from `Date.now()` and the server subtracts a `time.monotonic()` reading; the two have no common origin. Every other hop is sound because both its ends are server-side |
| Realised speed, real model at `--speed 1` | **0.99x** — 117.10 s wall for 116.40 s of stream | measured 2026-09-08 by Aymen on Apple silicon, `docs/slice4-last-test-report.json` | MEASURED. Says MLX **keeps up** with one real-time stream; says nothing about headroom. The headroom figure is still B1's 1.24x maximum throughput, and 0.99x at a 1x request cannot improve on it |
| `Meeting.asr_version` written by the app-server | **`kyutai/stt-1b-en_fr@mlx-bf16`** | measured 2026-09-08 by Aymen on Apple silicon, `docs/slice4-last-test-report.json` | MEASURED **through the running app-server**, not just the probe. Confirms the identity reaches the database by the seam rather than by a hard-coded string |
| Sentence-final words orphaned into their own segment | **8 of 30 segments (27%)** | measured 2026-09-08 by Aymen on Apple silicon, `docs/slice4-last-test-report.json`, derived | **MEASURED, and a defect** (L-28). Segment durations 160-400 ms holding one word. The acoustic gap before each is 160-560 ms, so **no** silence in the audio can explain a 1 200 ms silence close; the cause is the model's emission lag, not the recording |
| Hour of 4-person French, prompt size | **~37 000 tokens** (est.) against a 128 000 window | `tests/unit/test_prompt_budget.py`, 2026-09-08 | **ESTIMATED, not counted.** Tiles the real Slice 4 fixture to an hour; tokens derived from characters at 3 chars/token, chosen pessimistically. Answers A-5 and is why chunk-and-merge is not in Slice 5 |
| Share of the prompt spent on segment ids | **~42%** (46k of 111k characters) | same test | MEASURED (characters, not tokens). A 26-char ULID on every line costs more than the French. Not a defect — evidence links need real ids — but it is the first thing to shorten if a longer meeting nears the ceiling |
| Schema-rejection rate on real outputs | unknown | — | **AWAITING MEASUREMENT — needs an API key.** A-6's number. `FakeLLMProvider` cites real ids by construction and can only ever pass, so no run without a real provider produces this |
| Cost per meeting, real provider | unknown | — | UNMEASURED. Relevant because the pilot pays it per meeting; `gpt-4o-mini` at ~37k input tokens is the arithmetic to check once a real call has been made |
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
| `tests/unit/test_openai_provider.py` | the OpenAI adapter with no OpenAI: strict-schema translation over `$defs`, nullable optionals, request shape, and five malformed-response paths that must raise rather than return a blank summary | **13 passing** — against a fake transport, no key |
| `tests/unit/test_audio_range.py` | Range arithmetic (suffix, clamping, 416) and the store read path, including a timestamp seek landing on the right bytes and a key that escapes the root | **23 passing** |
| `tests/unit/test_prompt_budget.py` | Spike D: an hour of 4-person French against the context window (A-5) | **2 passing** |
| `tests/unit/test_l28_orphaned_final_word.py` | **a characterization test for a known defect.** Pins L-28's shape — 8 of 30 orphans, and that no acoustic gap explains them — so a deferred defect stays visible and fixing it is deliberate | **4 passing.** It asserts behaviour that is *wrong*; when it fails, update §10 rather than deleting it |
| `tests/integration/test_audio_playback.py` | FR-11 through real requests: 206 with the right `Content-Range`, 416 past the end, cross-tenant refusal, and the transcript carrying `audio_session_id` plus session epochs | **7 passing** against a real `LocalAudioStore` |
| `frontend src/audio/playback.test.ts` | PCM decode and the `byteOffset = ms x 48` arithmetic FR-11 rests on | **11 passing** (vitest) |
| `frontend src/review/evidence.test.ts` | citation resolution: session-epoch subtraction, gap segments shown as unplayable rather than dropped, ordering by when it was said | **11 passing** (vitest) |
| smoke (real model) | WER + p95 first-word latency on a French fixture through the app-server | **RUN 2026-09-08 on Apple silicon by Aymen — `docs/slice4-last-test-report.json`.** 116.36 s, 24 kHz mono, one participant, `--speed 1`, real MLX Kyutai. Exit 0, 30 segments, all persisted, sockets consistent, meeting `COMPLETED`. Produced the WER, first-word-latency and `asr_version` rows in §8 — and L-28. **A report, not a regression test: nothing re-runs it, and it needs hardware this repository's suite does not have** |
| cross-network run (A-8) | two physical machines, one meeting | **NOT RUN** — needs a second machine. `tools/replay --base-url` is the harness for it |
| `tests/unit/test_segmentation_against_real_audio.py` | the retuned §9.3 thresholds replayed through the real `Segmenter` over Spike B1's measured word timings | **5 passing.** Asserts the speaker's four sentences come out whole, that the old 700 ms threshold split phrases, and that **no** silence-only threshold reproduces them |
| `tests/unit/test_kyutai_adapter.py` | the Kyutai adapter with no Kyutai: identity, piece assembly, backoff, session health and liveness, moshi-server protocol translation | **34 passing** |
| `tests/unit/test_latency_decomposition.py` | the `capture -> ... -> broadcast` stages | **7 passing** |
| `tests/unit/test_asr_runtime_selection.py` | ADR-13 runtime selection, fail-fast | **5 passing** |
| `tests/unit/test_replay_fixtures.py` | a real WAV into the harness, and the wrong format refused | **6 passing** |
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
| L-24 | The sentence-end rule will split a French abbreviation | `M.`, `Mme.`, `etc.` end in a period without ending a sentence. None occurred in B1's 64 s, so the risk is real but unmeasured. The rule is a `Segmenter` argument, so turning it off is configuration rather than a code change | A fixture contains one, or a second speaker is measured |
| L-25 | `test_one_participant_dropping_does_not_disturb_the_other` failed once; **a plausible cause was found and removed**, but causation is unproven | Seen on the first full run after the Slice 4 changes, with no output captured, then not reproduced in 17 runs. Re-reading the diff afterwards turned up a real defect that fits: the runtime read the new end-of-turn capability with `getattr(asr, "emits_end_of_turn", False)`, and `FakeASRSession` did not declare it — so the fake, which *does* emit end-of-turn events, was silently given the punctuation fallback and every scripted phrase closed at its final word instead of at the event 60 ms later. That moved segment boundaries under a test whose injected disconnect lands at 6 400 ms, exactly a phrase boundary. The capability is now on the `ASRSession` Protocol with no default, the fake declares `True`, Slice 1-3 closing behaviour is exact again, and 3 further full runs pass. **A cause that fits, not a cause that was observed** — the original failure was never reproduced, so this is not called closed | Next time it fires. If it recurs now, the shared-database suspicion from L-22 is what is left |
| L-26 | The MLX runtime serves one stream at a time per process | `LmGen` holds the per-stream KV cache while the weights are shared, so two concurrent MLX sessions would interleave caches and corrupt both transcripts with nothing logged. A second session is refused with an error naming `moshi_server` instead. Slice 4 is single-stream by design and concurrency is A-3, which only a real serving runtime can answer | Spike B2, or four-participant work in Slice 6 |
| L-27 | **Half closed 2026-09-08.** The MLX path has now been executed against the real model — on Aymen's Apple silicon, never in this environment. `asr_runtime/moshi_ws.py` has still never met a server | `mlx_runtime.py` needs Apple silicon and `moshi_ws.py` needs a CUDA host. The MLX half moved from `IMPLEMENTED` to `VERIFIED` by a report that no test re-runs; the `moshi_server` half is still `IMPLEMENTED` on the strength of a fake transport alone | Spike B2 closes the other half. Neither half is covered by CI, because there is no CI (L-18) |
| L-28 | **The sentence-final word is orphaned into its own segment, 8 times in 30.** **DEFERRED BY DECISION 2026-09-08 (Aymen), not by oversight** — judged a contained edge case rather than a blocker, with Slice 5 to proceed against the finalized-segment contract and build no special cases around it. Reassess at the end of Slice 5, and only if it has shown real impact on meeting intelligence, evidence linking, or transcript correctness. Pinned meanwhile by `tests/unit/test_l28_orphaned_final_word.py`, a characterization test that fails the day the shape changes | Found 2026-09-08 in the first real fixture, and invisible to the WER that passed alongside it: the words are all correct and in order, so concatenated text scores 1.43% while the *segmentation* is wrong 27% of the time. **What the numbers prove:** the acoustic gap before each orphan is 160-560 ms, less than half the 1 200 ms threshold, so no silence in the recording can account for a single one of these closes — `on_tick` fired on silence that was never spoken. **What is inferred and not yet observed:** that `transcribed_offset_ms` — frames processed, minus the 500 ms configured delay — drifted past the last emitted word because the model withholds a sentence's final word while it settles the punctuation. That fits every case and fits nothing else obvious, but no log was captured showing the offset and the emission side by side, so it is a cause that fits rather than a cause that was seen. **Confirm it before fixing it:** log `transcribed_offset_ms` against the last word's `end_ms` at each tick on a re-run, which the §12 procedure can produce. Consequences are downstream, not cosmetic — segments are the unit of persistence (ADR-05), of speaker attribution, and of Slice 5's evidence links, and a 160 ms segment holding `tous.` is a poor citation. Not fixed here: the fix is a segmenter or adapter change, which is Slice 4 code work rather than the documentation this pass was asked for. Three candidate directions, none measured: gate the silence tick on emission lag rather than processed frames; have `MlxBackend` report a `transcribed_offset_ms` that accounts for its own withholding; or raise the silence threshold, which A-12's finding already says cannot separate the distributions on its own | **Before the transcript is used for anything.** It is the first thing Slice 5 will trip over, and it should be fixed with a regression test built from this fixture's word timings, the way §9.3 was retuned from B1's |
| L-29 | The `capture` → `gateway_recv` latency hop is meaningless — p95 reads ≈ 3.2×10⁹ ms | Clock domains, not a slow pipeline. The browser stamps `capture_ms` with `Date.now()` (Unix epoch) and the server subtracts a `time.monotonic()` reading (arbitrary origin), so the difference is the distance between two unrelated zeros. Every other hop is server-side at both ends and is sound, which is why the total that matters — gateway → broadcast, 1 343.46 ms p95 — is trustworthy. Harmless to transcription; actively misleading in a latency table, which is why it is named here rather than left for the next reader to rediscover | Whenever client-side latency genuinely needs measuring. The fix is a handshake offset or a server-stamped arrival time, not a bigger number |
| L-30 | ~~`backend/uv.lock` is missing the `mlx` extra~~ **CLOSED 2026-09-08.** Slice 5 added an `openai` extra, which was the trigger the entry named, so the lock was regenerated with `uv lock` and now carries all three extras. `uv run` no longer rewrites it | `pyproject.toml` gained an `mlx` extra in Slice 4 (ADR-13 consequence 5, correctly marked `sys_platform == 'darwin' and platform_machine == 'arm64'`), but the lock committed alongside it was never re-resolved: it contains no `mlx`, `mlx-metal` or `moshi-mlx` entry. uv resolves universally, so the fix adds all 27 of them with their darwin markers intact and changes nothing that installs on Linux. Reproduced here on 2026-09-08 — a bare `uv run python -c pass` is enough. Deliberately **not** committed in rev 12, which is a documentation pass; a 464-line lock diff does not belong in it, and whoever regenerates it should be the person who can then run the suite on both platforms | Next time anyone touches `backend/pyproject.toml`. One command: `cd backend && uv lock`, then commit the result on its own |
| L-31 | **No real LLM call has ever been made from this codebase** | The OpenAI adapter, its strict-schema translation and its five failure paths are all tested against a fake transport, which is the seam working as intended — but a fake transport cannot tell you that OpenAI accepts the body we build, that `gpt-4o-mini` honours the schema on real French, or what it costs. `IMPLEMENTED`, not `VERIFIED`, exactly as `moshi_server` is. The same shape of gap as L-27, on the other axis | Ten real meetings with `MOSAIQUE_LLM_PROVIDER=openai` and a key — §12. That run closes Slice 5's gate and answers A-6 |
| L-32 | The Playwright specs were not re-run against the new review page | Slice 5 changed `ReviewPage.tsx` substantially — evidence buttons, audio playback, a cited-segment highlight — and the two browser specs are carried forward from rev 9 unexecuted. The unit tests cover the logic those buttons call, but nothing has clicked one. `npm run test:e2e` needs a running backend and a browser, and this environment has neither reliably | Next local run. It is cheap and it is the only thing that would catch a review page that renders but does not respond |
| L-17 | `frontend/node_modules/` is tracked in git (4191 files) | Pre-existing; `.gitignore` covers new files but the old entries are still indexed, so an `npm install` dirties the tree. `__pycache__` was untracked on 2026-09-06 — 38 `.pyc` files, unambiguously build output, and they re-dirtied on every test run. `node_modules` is left alone: untracking it changes how a fresh checkout is bootstrapped, which is a call to make on its own | A deliberate decision about how dependencies are vendored |

---

## 11. Changelog

| Date | Change |
|---|---|
| 2026-09-08 | **rev 13. Slice 5 built: real provider, FR-11 audio, evidence links. No real call made.** Q2's provider half answered by Aymen — OpenAI `gpt-4o-mini`, chosen on available credit and **explicitly not on residency**, which stays open and is the half a French-SMB pilot will actually have to answer. The adapter follows the ADR-13 shape exactly: vendor translation in `intelligence/adapters/openai_chat.py` with no HTTP import, the client in a new `llm_runtime/` package, selection by typed config that fails fast on a missing key, and **two new architecture tests** holding the split — the LLM seam is now enforced the way the ASR one is rather than by convention. Structured outputs are pinned strict, which needed a schema rewrite (`additionalProperties: false` and full `required` on every object, `$defs` included, optionals as nullable) — done in the adapter so `MeetingIntelligence` stays written for our contract rather than bent around one vendor's decoder. **Spike D was run and said no**: an hour of 4-person French estimates at ~37k tokens against a 128k window, so chunk-and-merge was not built — the plan made it conditional and the condition failed. Its by-product is worth keeping: **42% of the prompt is segment ids**, a 26-char ULID per line costing more than the French. FR-11 shipped whole — `GET /meetings/{id}/audio/{session_id}` with Range support (206, suffix ranges, clamping, 416), a store read path that refuses keys escaping its root, `audio_session_id` and session epochs on the transcript payload, and a review page where a decision's citation scrolls to the segment and plays the moment. The offset is arithmetic, not an index: `segment.start_ms - session.epoch_ms`, which works only because ADR-11 stores the silence padding too. `meeting.outputs.ready` is finally emitted rather than merely defined, through an injected `Broadcaster` so `jobs/` stays transport-free — and a broken socket cannot fail a committed job, which has its own test because re-running a paid call to re-derive durable data is the failure worth preventing. **L-28 is deferred by Aymen's decision, and deferring it left a test rather than a note**: `test_l28_orphaned_final_word.py` pins the defect's exact shape — 8 of 30, no acoustic gap above 560 ms — and asserts nothing about its cause, which is still a hypothesis. Slice 5 builds no special case around it. Backend 262 -> 315, frontend 27 -> 49, `ruff`/`mypy`/`npm run build` clean, OpenAPI regenerated. **What is not claimed: no real LLM call has been made from this codebase** (L-31) — every test runs on a fake transport, so the ten-meeting gate and A-6's rejection rate both still need a key. The Playwright specs were also not re-run against the rewritten review page (L-32). L-30 closed on the way past: the lock now carries all three extras and `uv run` stops rewriting it. |
| 2026-09-08 | **rev 12. Slice 4 measured on real French audio; the gate closes, and one defect closes with it.** Aymen ran the §12 smoke test on Apple silicon: 116.36 s of French, 24 kHz mono, one participant, `--speed 1`, real MLX Kyutai through the running app-server — `docs/slice4-last-test-report.json`. **A-10 is answered: 1.43% WER** (349 reference words, edit distance 5, and all five edits are normalisation — `sept heures` → `7 heures` — rather than misheard speech). p95 first-word latency **1 934 ms**, inside the 2.0 s guess by 66 ms. The per-hop decomposition says where the time goes and it is not the plumbing: gateway → dequeue 0.15 ms, **dequeue → first ASR event 1 343.27 ms**, first event → broadcast 0.14 ms. `Meeting.asr_version` came back `kyutai/stt-1b-en_fr@mlx-bf16` **written by the app-server**, which is the seam demonstrating itself rather than being asserted. 30 segments, all persisted, sockets consistent, `COMPLETED`, exit 0. ADR-13's runtime policy is now written into `CLAUDE.md` where a new session will read it: MLX is the development runtime, not an infrastructure decision, and `moshi_server` sits behind the same `KyutaiBackend` Protocol so replacing it stays a config change. **Two things this run found that the verdict does not say on its own.** The WER hides a segmentation defect: 8 of the 30 segments are a sentence's final word alone in a 160-400 ms segment, because MLX withholds that word while it settles the punctuation and `transcribed_offset_ms` drifts more than 1 200 ms past it — the acoustic gap before each orphan is 160-560 ms, so no silence in the recording can account for a single one. That is **L-28**, recorded and *not* fixed: it is code, and this pass was asked for documentation. It also makes A-14 partially answered *against* itself — the first real jitter this system has seen broke the first threshold it met. Second, `capture` → `gateway_recv` reads ≈ 3.2×10⁹ ms because the browser's `Date.now()` is being subtracted from the server's `time.monotonic()`; the metric is broken, not the pipeline (**L-29**), and every hop with both ends server-side is sound. L-27 is half closed: the MLX path has now run against the model, on Aymen's Mac and nowhere else, so Slice 4 is `VERIFIED` by a report that **nothing re-runs** — there is still no CI (L-18) and this environment has no Apple silicon. Backend suite re-run here unchanged: `262 passed, 1 deselected in 88.52s`. No code was modified in this revision. |
| 2026-09-08 | **rev 11. Spike B1 run; Slice 4 built but not measured.** B1 ran on an M1 and closed A-2 partly against itself: no retraction in 825 steps, 24 kHz/80 ms confirmed, the 500 ms delay and a 0 ms silence prefix **read from the build** rather than assumed — and **the semantic VAD absent from the `-mlx` weights**, which was the half of A-2 nobody expected to be wrong. A-12 answered **negatively**: 1.24x realised, so the D-05 flush trick has nothing to catch up with on MLX. Then Slice 4: the Kyutai adapter behind `StreamingRecognizer` with `mlx` and `moshi_server` backends chosen by typed config; bounded reconnect; `health()`; the `capture -> gateway_recv -> dequeue -> asr_first_event -> broadcast` decomposition; `Meeting.asr_version` recording model, runtime **and** quantization. §9.3 was retuned against B1's real word timings *before* the adapter was written, and the retune found something the fake could never have shown: this speaker's largest mid-phrase pause (1 120 ms) is longer than their shortest real sentence break (880 ms), so **no silence threshold separates them**, and the 700 ms default was splitting phrases six times a minute. Silence moved to 1 200 ms and sentence-final punctuation became a closing rule — necessary because on MLX there is no end-of-turn event to fall back on. Backend suite 189 -> 260 with **no Slice 1-3 test modified**, which is the seam's proof. Two deviations recorded rather than smuggled: the ASR timeout is now a liveness check on frames *processed*, because "no event for 5 s" fires on any pause when 663 of 825 steps emit nothing; and `moshi-server`'s socket lives in a new `asr_runtime/` package because `speech/` may not import a transport, with two new architecture tests holding both halves of that. One defect was found by re-reading the diff rather than by a test: the runtime discovered the new end-of-turn capability with a `getattr` default, so the fake — which does emit end-of-turn events — was silently given the punctuation fallback and its phrases closed 60 ms early. The capability now sits on the `ASRSession` Protocol with no default and Slice 1-3 closing behaviour is exact again; it also fits L-25, though the original failure was never reproduced and so is not called closed. **Nothing in the model path has been executed here** (L-27): WER and p95 first-word latency are `AWAITING MEASUREMENT` against Aymen. |
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

### Slice 4 — the gate is closed. This is now the re-run procedure

**Run 2026-09-08 by Aymen on Apple silicon; results in `docs/slice4-last-test-report.json`
and written into §8.** Keep this runbook: it is how you reproduce the numbers
after any change to the adapter, the segmenter or the thresholds, and it is the
only procedure that puts a real model in the path. It still needs Apple silicon,
so no session running in the web sandbox can execute it — ask Aymen.

Two things to know before trusting a re-run. There is no reference transcript in
the repository, so Step 6's WER needs the golden `.txt` that goes with whichever
fixture you use. And the numbers this produces describe **one speaker, one
stream, bf16 on Apple silicon** — A-16 says they do not transfer to CUDA, and
nothing here has ever run two real streams at once (L-26).

**Step 0 — record the fixture, if you have not.** Three minutes of French, the
microphone you would really use, several clear sentence ends and a couple of
mid-sentence pauses. **Write down verbatim what you said** in a `.txt` beside
it: without a reference there is no WER, which is exactly why B1 could not
produce one. Then put it in the canonical format:

```bash
ffmpeg -i your-recording.m4a -ac 1 -ar 24000 -sample_fmt s16 fr-slice4.wav
cd backend
uv run python -m tools.replay convert fr-slice4.wav tests/fixtures/audio/fr-slice4.pcm
```

**Step 1 — install, including the MLX extra.**

```bash
cd backend
uv venv && uv pip install -e ".[dev,mlx]"
uv run alembic upgrade head
```

**Step 2 — check the seam still holds before involving the model.** This is the
run that proves `FakeRecognizer` was not disturbed, and it needs no GPU:

```bash
uv run pytest -q                      # 260, PostgreSQL required
uv run ruff check . && uv run mypy    # clean, 88 files
```

**Step 3 — start the app-server on the real runtime.** It preloads the weights,
so **it will sit on `asr_runtime_preloading` for a few minutes** the first time
(B1 measured 284 s cold). That is the fix for a worse problem: paying it inside
the first meeting instead would stall a live participant.

```bash
export MOSAIQUE_ASR_RUNTIME=mlx
export MOSAIQUE_ASR_MODEL_REPO=kyutai/stt-1b-en_fr-mlx
uv run uvicorn mosaique.app.main:create_app --factory --port 8000
```

**Step 4 — replay the fixture at real time, in another shell.**

```bash
cd backend
uv run python -m tools.replay run tools/replay/scenarios/french-real.json \
  --host-token "$(uv run python -m mosaique.app.seed | tail -1)" \
  --speed 1.0 --report /tmp/slice4.json
```

**Step 5 — read the three things off it.**

```bash
# p95 first-word latency, and the transcript the model produced
python3 -c "import json;r=json.load(open('/tmp/slice4.json'));print(r['totals']);print(*[s['text'] for s in r['segments']],sep=chr(10))"

# the per-hop decomposition: the app-server logs one record per meeting
#   grep it in the uvicorn output
#   latency_decomposition stages_ms={...}

# what produced the words — must read kyutai/stt-1b-en_fr@mlx-bf16
psql mosaique -c "select asr_version, transcript_version from meetings order by created_at desc limit 1;"
```

**Step 6 — WER, by hand, once.** Compare the printed segments against your
reference `.txt`. Word error rate is
`(substitutions + insertions + deletions) / reference words`. Report it with the
`asr_version` string beside it or the number means nothing later (ADR-13 §2).

**Step 7 — look at the segment boundaries, not only the words.** WER cannot see
segmentation: the 2026-09-08 run scored 1.43% while orphaning the last word of 8
sentences into their own 160-400 ms segments (L-28). Read the `segments` array
in the report and check that no segment holds a single word ending in a period.

### Slice 5 — closing the gate needs a key

Everything else in Slice 5 is merged and tested. These two rows of the exit
gate are the ones a fake provider provably cannot produce.

```bash
# from backend/, with a real key. `fake` stays the default everywhere else.
export MOSAIQUE_LLM_PROVIDER=openai
export MOSAIQUE_LLM_API_KEY=sk-...          # startup fails fast without it
export MOSAIQUE_LLM_MODEL=gpt-4o-mini       # ~37k input tokens per hour-long meeting

uv run uvicorn mosaique.app.main:create_app --factory --port 8000
# then run ten meetings through it — the replay harness is the cheap way:
uv run python -m tools.replay run tools/replay/scenarios/two-participants.json \
  --host-token "$(uv run python -m mosaique.app.seed | tail -1)" --speed 10
```

**What to send back**, and why each one:

1. **The schema-rejection rate over ten meetings** — A-6. Count runs where
   `validate_outputs` raised, and split `schema` from `unknown_evidence`: the
   first means strict mode did not hold, the second means the model cited a
   segment nobody spoke. They have different fixes.
2. **Whether the body is accepted at all.** L-31: a fake transport cannot tell
   us OpenAI likes our request. A 400 on the first call is the most likely
   failure and the cheapest to find.
3. **Cost per meeting.** The pilot pays it per meeting and nobody has seen the
   number.
4. **Whether the French is any good.** Not in the gate, and it is the thing a
   customer would notice first.

Also worth a local run while you are there: `npm run test:e2e` against the
rewritten review page (L-32), and clicking one citation to confirm FR-11 works
in a browser rather than only in tests.

### What to pick up next

In the order a new session should consider them.

1. **L-28, the orphaned sentence-final word.** **Deferred by decision** — do
   not reopen it on your own. Reassess only at the end of Slice 5, and only if
   it has shown real impact on meeting intelligence, evidence linking or
   transcript correctness. Until then `test_l28_orphaned_final_word.py` holds
   its shape and Slice 5 builds no special case around it. The old entry: the fix wants a regression
   test built from the fixture's word timings, the way §9.3 was retuned from
   B1's, and whether it reopens Slice 4 or opens a 4b is Aymen's call.
2. **Slice 6 — four participants, observability, load**, per
   `docs/IMPLEMENTATION_PLAN.md`, once Slice 5's gate is closed. Note that MLX
   cannot serve two streams at once (L-26), so four real participants need the
   CUDA host Spike B2 is already waiting on.
3. **Still hardware-blocked, all pre-existing.** Spike B2 and A-3 (CUDA host,
   also the only way to test `moshi_server`, `EndOfTurnEvent` and A-16); the
   cross-network run A-8 (a second machine); Spike A (two laptops and real
   microphones); the GPU half of A-9 (a long real-model run).
4. **L-18 — there is still no CI.** Every claim in this document is local-only.
   It is Slice 0 work and it does not get smaller by waiting.

**Send back:** p95 first-word latency, the `latency_decomposition` line, WER,
the `asr_version`, and — added after L-28 — whether any segment holds a single
word ending in a period. The 2026-09-08 run sent back the first four and the
fifth is why it is on the list.

**Still blocked, and not by this slice:** Slice 6 needs a CUDA host for Spike B2
(A-3, A-4, and A-16's other half). `moshi_server` is implemented and has never
touched a server.
