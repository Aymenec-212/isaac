# PROJECT_STATE.md

**Project:** Mosaïque — realtime meeting intelligence, French-first
**Last updated:** 2026-09-09 (rev 21 — Slice 6R specified)
**Updated by:** Slice 6R session
**Current slice:** **Slice 6R — single-user review hardening. PHASE A.**
Specified 2026-09-09 at Aymen's direction and **not yet implemented** — see
`docs/IMPLEMENTATION_PLAN.md` v1.4. Slice 6A is five of six done (health
endpoints, transcript search, A-14 under real emission timing, the full-lifecycle
test, degraded-state UX); its last item, the **§15 metrics, is deliberately
sequenced after 6R**, so 6A now closes after it rather than before.

**Why 6R exists.** PR #14 validated on the M1 and the review experience was the
next thing named: *"before moving on to the two users and serving the ASR model on
a CUDA runtime, we first need to prioritize the single user experience"*. The
concrete failure is that `ReviewPage` renders one paragraph per segment with the
speaker repeated on each — an hour of French is ~930 labelled lines, 8 in 30 of
them a single orphaned word (L-28). That is a log, not a transcript.

**Rev 20 exists because a person ran the app and a test suite could not have.**
Aymen took the M1 build, put each dependency down by hand, and found that with
the ASR runtime unavailable the banner said *Service indisponible* while
**Nouvelle réunion** stayed clickable. The readiness verdict was computed
correctly and asserted six times — and had no consumer (L-35).

*(Header revision drifted between rev 14 and rev 17: changelog rows were appended
without bumping this line. Corrected in rev 18; §11 is the authoritative history.)*

**The plan was re-sequenced on 2026-09-08** (`docs/IMPLEMENTATION_PLAN.md` v1.3).
The remaining work now splits into three phases: **A** hardens the complete
single-user product on M1 + MLX, **B** validates the production serving path on a
dedicated NVIDIA host, **C** delivers four participants. Slice 6's requirements
were **split, not reduced** — every original item and every exit-gate clause
appears in exactly one of 6A / 6B / 6C.

What this changes here: **"MLX cannot serve four streams" (L-26) is no longer an
immediate blocker.** MLX is sufficient for the Phase A track and disqualifying
for Phase C, and both were always true; what changed is that Phase C is no longer
the next thing. The four-participant requirement is unchanged as a later
acceptance target.

**Slice 5 is now confirmed working against the real provider** — Aymen, 2026-09-08
— which closes the half of L-31 that mattered most: the request body OpenAI
receives is accepted, and the outputs are usable. The gate's *numbers* are still
unmeasured; see L-31 and A-6 for exactly what is and is not claimed.

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

### Validation environment — where a claim was proven

Added 2026-09-08 with the Phase A/B/C re-sequencing. `VERIFIED` alone stopped
being precise enough once two runtimes existed: a number measured on MLX does not
describe CUDA (A-16), and a loopback run does not describe a network (A-8). Every
status below therefore says **where** as well as **whether**.

| Mark | Means | What it does *not* mean |
|---|---|---|
| ✅ **M1 + MLX** | Verified locally on Apple silicon against the real MLX Kyutai runtime. | Nothing about CUDA, `moshi-server`, or more than one concurrent stream. |
| ✅ **fake** | Verified by an automated test on `FakeRecognizer` / `FakeLLMProvider`. | Nothing about a real model. The seam is proven; the model is not. |
| ⚠ **implemented, not validated** | Code merged, plausibly correct, no run behind it. | Do not cite it as evidence for anything. |
| ❌ **needs NVIDIA + `moshi-server`** | Cannot be validated on any hardware this project currently has. | Not a defect — a procurement dependency. Phase B. |
| ❌ **needs cross-network** | Needs two physical machines. Every run so far is loopback. | Not a defect. A-8. |

**The production GPU serving path is not marked verified until it has actually
served a meeting.** No amount of passing fake-transport tests changes that, and
the same rule already applies to the LLM provider and to `moshi_server`.

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
| Repository | `main` through PR #12 (rev 18 handoff). Work branch `claude/sharp-dijkstra-uf34s8`, restarted from `main` after each merge |
| Runnable | yes — `docker compose up`, or uv + local PostgreSQL |
| Deployed | no |
| Real audio ever transcribed by this system | **yes, once, end to end.** 116.36 s of French through the running app-server against real MLX Kyutai on Apple silicon, 2026-09-08 — `docs/slice4-last-test-report.json`. 1.43% WER, 30 segments, all persisted, meeting `COMPLETED`. One speaker, one stream, one machine, and never in this environment (L-27) |
| Tests passing | **474**: 305 backend unit, 77 backend integration and realtime (real PostgreSQL), 79 frontend unit, 8 Playwright browser specs — **all four suites re-run by Aymen on 2026-09-08, Playwright included**. Plus one opt-in accelerated hour behind `-m slow`. **Re-run by Aymen on his M1, 2026-09-08 — all green.** Backend `380 passed, 1 deselected`, matching this sandbox exactly; measured-timing and reconnect/idle/health subsets green; frontend `72 passed`; PostgreSQL healthy in Docker; **`/readyz` ready with MLX weights and database healthy**; frontend serving on `127.0.0.1:5173`. `npm run build` clean. **Rev 19 adds two, in this sandbox on Linux:** backend `382 passed, 1 deselected in 104.73s` with `tests/integration/test_full_lifecycle.py`, frontend `72 passed` and `npm run build` clean, unchanged because no frontend file was touched. The accelerated hour still passes behind `-m slow` — `1 passed, 382 deselected in 70.58s`. **Rev 20 re-ran the browser suite in this sandbox and it is now 8 specs, all passing** — the 2 pre-existing ones included, since `App.tsx` and `MeetingList.tsx` both changed. Frontend unit 72 -> 79. **None of these executes a model or a provider**: the ASR evidence is a report (L-27) and the LLM's numbers have never been counted (L-31) |
| Lint / types | ruff clean; ruff format clean (144 files); mypy strict clean on **97** source files; `tsc --noEmit` clean; `openapi.json` regenerated with no drift (10 paths). *The 97 corrects a stale 88 — the count grew across Slices 5 and 6A and this line was never updated; rev 19 changed no source file, only re-read the number* |
| Known gap | A-8 unvalidated: every run so far is loopback on one machine. Spike A not run. A-3, A-16 and `moshi_server` all still need a CUDA host. **No CI runs on this repository** — see L-18, which now also means the one run that proves Slice 4 is reproducible only by hand, on hardware. |
| Next action | **Slice 6R — single-user review hardening.** Specified, not built: readable grouped transcript, interim/final distinction that does not rely on colour, speaker grouping and timestamps, failed *and* degraded summary states, and additive transcript corrections (Q9, now answered). Items 4 and 5 of the list — citations and search highlighting — already work and are **regression constraints**, because grouping is exactly what breaks them. **6A's last item, the §15 metrics, comes after this.** Needs Aymen's M1 and unchanged: real-time factor, first-word and final-segment latency, memory growth, long-run MLX stability. **Start from §12** |
| Next gate | **Slice 6R exit:** an hour-long transcript renders as speaker-grouped paragraphs with timestamps rather than one line per segment, asserted over a realistic segment count; interim and final are distinguishable without colour; citations still scroll and seek and search still highlights, both with grouping in place; failed and degraded summaries render distinctly; a correction round-trips with the raw ASR text still retrievable afterwards. **Then Slice 6A exit:** a realistic single-user meeting runs repeatedly on M1 + MLX with a trustworthy transcript and outputs; search returns the right segments; `/readyz` distinguishes each dependency being down; the seven §1.3 criteria that need no concurrency have named tests; every single-stream `[measure]` row has a number. **Slice 5's gate is still open on its numbers** — ten meetings and A-6's rejection rate — and is now tracked as Phase A work rather than as a blocker |

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
| Q9 | Transcript corrections in scope | product | **Slice 6R** | ~~out of scope~~ → **in scope, additive only** | **ANSWERED 2026-09-09 by Aymen**, who put "manual correction or annotation of transcript segments" in the Slice 6R priority list. This reverses a standing default that had held since 2026-09-03, so it is recorded as a decision rather than absorbed. **The shape is constrained by the slice's design principle:** the raw ASR text and its word timings are never overwritten — a correction is stored alongside, with authorship and a timestamp, and the review view shows the corrected text by default while still being able to reveal what the model said. Destructive editing would make L-28, the 1.43% WER and every `[measure]` row unfalsifiable after the fact. **Still open inside the slice:** whether correcting a cited segment should invalidate or re-run the meeting intelligence that quotes it — a paid LLM call and a product call, deliberately not automatic |
| Q7 | Stack confirmation | product | all | as specified | OPEN |
| Q1 | Companion vs carrier | product | everything | — | **CLOSED 2026-09-03 → companion** |

---

## 4. Functional requirements — intended vs. real

| FR | Requirement (PRD §17) | Intended in | Status | Evidence | Notes |
|---|---|---|---|---|---|
| FR-01 | Meeting creation with unique ID | Slice 0/1 | **VERIFIED** | `test_create_meeting_then_read_it_back` | ULID; `organization_id` from migration 1 |
| FR-02 | Continuous microphone capture | Slice 1 | **VERIFIED** | `e2e/meeting.spec.ts`, `e2e/two-participants.spec.ts` (Chromium fake device) | AudioWorklet 48→24 kHz, 80 ms frames |
| FR-03 | Realtime transcription | Slice 1 (fake) / Slice 4 (real) | **VERIFIED, fake and real** | `test_speaking_produces_live_interim_then_final_segments`; real model in `docs/slice4-last-test-report.json` (1.43% WER) | The real half is a report no test re-runs (L-27) |
| FR-04 | Interim and final events | Slice 1 | **VERIFIED** | `tests/unit/test_segmenter.py` (12), `reconciler.test.ts` (11), flow test asserts both statuses | |
| FR-05 | Speaker association | Slice 2 | **VERIFIED (endpoint capture)** | `test_the_harness_merges_two_attributed_streams`, `e2e/two-participants.spec.ts` | Two streams, each segment under its own speaker, in both browsers. Attribution when one microphone hears another person is Spike A and is **not** covered (L-2) |
| FR-06 | Finalized transcript | Slice 1 | **VERIFIED** | `test_only_final_segments_reach_the_database`, `test_startup_recovery_completes_a_stranded_finalizing_meeting`, and — as one walk rather than as pieces — `test_a_meeting_runs_from_creation_to_a_reviewable_record` | |
| FR-07 | Meeting summary | Slice 1 (fake) / Slice 5 (real) | **VERIFIED (fake only)** | `test_processor_produces_evidence_linked_outputs` | The real provider is merged and unit-tested but has never been called (L-31) |
| FR-08 | Action item extraction | Slice 1 (fake) / Slice 5 (real) | **VERIFIED (fake only)** | same test; evidence ids checked against real segments | Same caveat as FR-07 (L-31) |
| FR-09 | Decision extraction | Slice 1 (fake) / Slice 5 (real) | **VERIFIED (fake only)** | same test | Same caveat as FR-07 (L-31) |
| FR-10 | Transcript review and search | read: Slice 1, search: Slice 6A | **VERIFIED** ✅ fake | `GET /transcript?q=` — `test_transcript_search.py` (18), 4 route tests, `highlight.test.ts` (12). Accent-insensitive, a deliberate deviation from §6's "ILIKE for now" because French. Meeting-scoped only — L-33 | |
| FR-11 | Timestamp navigation | Slice 5 | **VERIFIED (server side); browser side untested** | `tests/integration/test_audio_playback.py` (7), `playback.test.ts` (11), `evidence.test.ts` (11), `test_full_lifecycle.py` (2) | Range route, offset arithmetic and citation resolution all covered. The lifecycle test adds the leg the others could not: citations the *summarizer* actually produced, resolved to a byte range that really exists — earlier tests supplied their own ids. Nobody has clicked a citation in a real browser — L-32 |

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
| `speech/adapters/fake/measured.py` | A-14 | **VERIFIED** ✅ fake | `test_measured_timing.py` (11), `test_measured_thresholds.py` (4). Replays a real MLX run's emission timing so the runtime meets genuine jitter without hardware. Still a fake: no model, no weights, runs on Linux |
| `speech/adapters/kyutai/mlx_runtime.py` | ADR-13 | **VERIFIED, by report only** | `docs/slice4-last-test-report.json` — 116 s of real French at 1x, 2026-09-08. Verified by a run, not by a test: needs Apple silicon, so neither this environment nor CI can execute it (L-27). One stream at a time by design (L-26) |
| `asr_runtime/moshi_ws.py` | §9.2 | **IMPLEMENTED** | Needs a CUDA host running `moshi-server`. The protocol logic it carries is tested; the socket and msgpack framing are not |
| `transcript/search.py` + `GET /transcript?q=` | FR-10, §6 | **VERIFIED** ✅ fake | `test_transcript_search.py` (18), `test_meetings_api.py` search cases (4), `highlight.test.ts` (12). Accent-insensitive; returns match offsets so the highlight cannot disagree with what matched |
| `observability/health.py` + `/readyz`, `/health/deps` | §15 | **VERIFIED** ✅ fake + ✅ M1 + MLX | `test_health_probes.py` (11), `test_health_endpoints.py` (10), and readiness checks passed against the **real MLX runtime** in Aymen's 2026-09-08 manual run. Per-dependency; the LLM provider is listed and does not gate readiness, per §15 |
| `StreamingRecognizer.readiness()` | §15, §9.1 | **VERIFIED** ✅ fake | `test_recognizer_readiness.py` (7). On the Protocol with no default, so a runtime cannot be silently assumed ready (the L-25 lesson) |
| `frontend src/health/` banner + `ReadinessProvider` | §15 | **VERIFIED** ✅ fake | `status.test.ts` (18), `e2e/degraded.spec.ts` (6). The blocked and degraded states are now **rendered and asserted in a browser**, which is what closed L-35: the banner used to own the only copy of the readiness verdict, so `MeetingList` never saw it. One poll now feeds both |
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
| A-3 | `moshi-server` handles concurrent streams | Fall back to PyTorch adapter | **Slice 6B** | ❌ **needs NVIDIA + `moshi-server`.** Concurrency is a property of the serving runtime, not the model, so no amount of MLX work touches it. **Re-sequenced 2026-09-08 into Phase B** — it gates Slice 6C, not the current track |
| A-4 | One GPU sustains 4 real-time streams | Ceiling and cost change | Spike C (half day) | **LARGELY ANSWERED** — vendor figure ~400 real-time streams per H100; confirm on our hardware |
| A-12 | Flush trick available through the adapter | Final-segment latency reverts to model delay | Spike B1 | **ANSWERED NEGATIVELY for MLX, 2026-09-08.** 1.24x realised, below the 1.5x it needs. `MlxBackend.flush()` pushes silence and waits rather than accelerating. Unchanged by the 116 s run, which realised 0.99x at a 1x request — that measures keeping up, not headroom, and cannot exceed B1's maximum. Still open for `moshi_server`, which has the `Marker` primitive but no hardware to run on |
| A-5 | 60-min transcript fits one LLM context | Chunking moves into Slice 5 | Spike D | **ANSWERED AFFIRMATIVELY 2026-09-08, by arithmetic.** An hour of 4-person French estimates at ~37k tokens against `gpt-4o-mini`'s 128k window — `tests/unit/test_prompt_budget.py`, which tiles the real Slice 4 fixture rather than inventing one. **Chunk-and-merge was therefore not built.** Tokens are estimated from characters at a deliberately pessimistic 3 chars/token, not counted with the vendor's tokenizer; the margin is ~3x, so the estimate does not need to be tight to be decisive |
| A-6 | LLM returns valid `evidence_segment_ids` | Evidence linking softens | Slice 5 / Phase A | **PARTIALLY ANSWERED 2026-09-08.** A real run worked (L-31), so strict mode plus `validate_outputs` holds on at least one real French meeting — ✅ M1 + MLX, once. The **rate** is still unmeasured: it is a count over ten meetings, split into `schema` failures (strict mode did not hold) and `unknown_evidence` failures (the model cited a segment nobody spoke), and those have different fixes. `FakeLLMProvider` cites real ids by construction and can only ever pass, so the number cannot be simulated |
| A-7 | Worklet resampling is cheap on mid-range laptops | Resample server-side | Slice 1 | UNVALIDATED — the e2e runs the worklet but measures no CPU cost |
| A-8 | 12.5 frames/s per participant survives real networks | Batch or enlarge frames | Slice 2 | **UNVALIDATED — the one Slice 2 exit-gate item still open.** Every run so far is loopback on one machine. `tools/replay --base-url` against a second machine is the test; it has not been run |
| A-9 | 30 s ASR grace does not leak GPU memory | Shorten grace | Slice 3 | **STILL PARTIAL.** `test_an_hour_of_meeting_does_not_grow_the_runtime` measures 0.0 MB of tracked growth across an accelerated hour on the *fake*. The 2026-09-08 MLX run put a real model in the path but ran 116 s and never exercised the grace window, so it says nothing about this. Needs a long real-model run, or Spike B2 |
| A-10 | French WER is good enough to be useful | Model swap | Slice 4 smoke test | **ANSWERED AFFIRMATIVELY 2026-09-08 — 1.43% WER** on 116 s of French through the app-server against a hand-written reference (`docs/slice4-last-test-report.json`). No model swap needed. Scope of the answer: one speaker, one prepared monologue, clean audio, no cross-talk and no second participant — the easiest case this product will ever see, so it is a ceiling rather than an expectation |
| A-11 | "Joining is consent" satisfies FR/EU law | Consent flow and DPA change | legal counsel | **UNVALIDATED — not an engineering question** |
| A-14 | Slice 3's thresholds hold against a recognizer whose timing is not a fixed script | Reconnect grace, idle close, overload window and gap threshold all need retuning together | Slice 4 / 6A | **LARGELY ANSWERED 2026-09-08 — ✅ fake, with real timing.** `MeasuredRecognizer` replays the emission timing of an actual MLX run (162 tokens from `docs/mosaique-b1-main/`), so the runtime now meets word gaps of p50 320 ms / p95 1 280 ms / **max 24 s** instead of a metronome. Under that: a meeting still transcribes in order, the 24 s hole does **not** trigger an idle close (it is keyed to frames, not events), a reconnect mid-burst neither duplicates nor loses segments, and ending mid-burst still flushes the pending tail — `tests/realtime/test_measured_thresholds.py` (4), `tests/unit/test_measured_timing.py` (11). What remains genuinely unanswerable without hardware: the same thresholds under MLX's *compute* jitter over hours. Earlier finding, unchanged: **PARTIALLY ANSWERED, and one threshold has already failed.** The 116 s run exercised real jitter for the first time: nothing dropped, nothing overloaded, no gap marker, `COMPLETED`. But the 1 200 ms silence threshold **did** fail against real emission timing — it closed 8 segments on silence that is not in the audio (L-28). Reconnect grace, idle close and the overload window were never provoked in 116 s and remain untested against a real model |
| A-15 | Per-participant runtime tasks do not corrupt shared state | A concurrency bug that no fast test can see | Slice 3 | **PARTIALLY VALIDATED, and it already failed once.** The persistence buffer was shared across participant pumps and dropped a broadcast segment; found by the two-stream accelerated hour, not by the unit suite. Other shared runtime state — the roster, `_stream_status`, `_file_frames` — is mutated from the same tasks and has no equivalent test. **`test_full_lifecycle.py`'s second test does not touch this**, and the distinction matters: it runs two meetings *sequentially* through one process, which catches state carried forward between meetings, not two pumps racing inside one |
| A-16 | MLX and CUDA runtimes produce equivalent transcripts within a stated tolerance | Every number measured on MLX has to be re-measured before it can describe production | **Slice 6B** | ❌ **needs NVIDIA + `moshi-server`.** Now explicitly Phase B work rather than an open-ended spike. It is also the reason §8 rows say which runtime they were measured on. ADR-13 M-7 asked for this to be recorded as "A-14", but A-14 was already taken by Slice 3's threshold assumption; it is A-16 here, and the ADR is the document that is wrong |
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
| `tests/integration/test_full_lifecycle.py` | **the chain, not its links.** One test walks create → join → speak → end → finalize → summarize → review and asserts what each step hands the next: the JOINABLE → LIVE transition, interim *and* final segments broadcast live and attributed, `asr_version` written on end, one AudioSession with frames counted, exactly one job enqueued, `meeting.outputs.ready` reaching a socket that is still open, then every cited segment resolved the way `evidence.ts` resolves it — segment → recording → epoch → byte offset — and a 206 Range at that offset returning the same bytes as the whole body. A second test runs two meetings back to back through one process and asserts neither carries the other's segments or anchor. Driven by `MeasuredRecognizer` over a `LocalAudioStore`, so the boundaries are a real MLX run's and the audio a citation names actually exists | **2 passing** in ~4.5 s. ✅ **fake only** — no weights, no provider. Checked against two deliberate breaks rather than assumed load-bearing: dropping `audio_session_id` at the insert, and making `fold()` accent-sensitive, each fails it. Run five times consecutively for flakiness (4.50–4.62 s, all green), because with no CI a flaky test is found by a person |
| `tests/integration/test_audio_playback.py` | FR-11 through real requests: 206 with the right `Content-Range`, 416 past the end, cross-tenant refusal, and the transcript carrying `audio_session_id` plus session epochs | **7 passing** against a real `LocalAudioStore` |
| `frontend src/audio/playback.test.ts` | PCM decode and the `byteOffset = ms x 48` arithmetic FR-11 rests on | **11 passing** (vitest) |
| `frontend src/review/evidence.test.ts` | citation resolution: session-epoch subtraction, gap segments shown as unplayable rather than dropped, ordering by when it was said | **11 passing** (vitest) |
| `tests/unit/test_measured_timing.py` | the measured-timing fixture and recognizer: word-to-token pairing, speed invariance, `transcribed_offset_ms`, flush releasing the pending tail, looping without going backwards | **11 passing** |
| `tests/realtime/test_measured_thresholds.py` | **A-14 through the real runtime** under emission timing from an actual MLX run: ordered transcript under bursts, the 24 s hole not triggering an idle close, reconnect mid-burst neither duplicating nor losing, and finalization flushing the tail | **4 passing** |
| `tests/unit/test_transcript_search.py` | FR-10 matching: accent folding that preserves length, offsets that slice the *original* text, non-overlapping repeats, blank queries returning the whole transcript | **18 passing** |
| `frontend src/review/highlight.test.ts` | rendering a hit: spans that arrive reversed, negative, out of range or overlapping must never alter the transcript text | **12 passing** (vitest) |
| `tests/unit/test_health_probes.py` | readiness logic with injected probes: a probe that raises, one that hangs, concurrency, stable ordering, and that a failing LLM provider does not block readiness | **11 passing** |
| `tests/unit/test_recognizer_readiness.py` | `RecognizerReadiness` per runtime: the fake is ready, an unpreloaded Kyutai runtime is `unknown`, a failed load reports its reason, and `moshi_server` stays `unknown` rather than vouching for a server nobody has reached | **7 passing** |
| `tests/integration/test_health_endpoints.py` | `/livez`, `/readyz`, `/health/deps` against a real app: 503 naming the blocker, `unknown` failing readiness, `/health/deps` staying 200 when a dependency is down, and a raising probe not taking the endpoint with it | **10 passing** |
| `frontend src/health/status.test.ts` | what the banner tells a person: blocked vs degraded, leading with what stops the meeting rather than what delays the summary, unknown dependencies still surfaced — **plus, from rev 20, `meetingCreationBlocked` and its reason line**, including that a check still in flight does not block, that an LLM-only outage does not, and that it agrees with `bannerFor` on every payload | **18 passing** (vitest) |
| `e2e/degraded.spec.ts` | **the banner's failure states, rendered.** ASR down and database down each block creation and say why; an LLM-only outage warns and still allows it; an unanswered `/readyz` blocks; a healthy server shows no banner and creates a meeting; recovery re-enables the button without a reload | **6 passing** against a real backend, `/readyz` stubbed in the browser. Checked against the pre-fix code: **4 of the 6 fail**, and the 2 that pass are exactly the two describing behaviour that was already correct |
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
| L-26 | The MLX runtime serves one stream at a time per process. **Not an immediate blocker as of 2026-09-08** — it gates Phase C, and Phase A is the current track | `LmGen` holds the per-stream KV cache while the weights are shared, so two concurrent MLX sessions would interleave caches and corrupt both transcripts with nothing logged. A second session is refused with an error naming `moshi_server` instead. Slice 4 is single-stream by design and concurrency is A-3, which only a real serving runtime can answer | **Slice 6C**, which is gated on Slice 6B's GPU host. Unchanged as a requirement; re-sequenced, not reduced |
| L-27 | **Half closed 2026-09-08.** The MLX path has now been executed against the real model — on Aymen's Apple silicon, never in this environment. `asr_runtime/moshi_ws.py` has still never met a server | `mlx_runtime.py` needs Apple silicon and `moshi_ws.py` needs a CUDA host. The MLX half moved from `IMPLEMENTED` to `VERIFIED` by a report that no test re-runs; the `moshi_server` half is still `IMPLEMENTED` on the strength of a fake transport alone | Spike B2 closes the other half. Neither half is covered by CI, because there is no CI (L-18) |
| L-28 | **The sentence-final word is orphaned into its own segment, 8 times in 30.** **DEFERRED BY DECISION 2026-09-08 (Aymen), not by oversight** — judged a contained edge case rather than a blocker, with Slice 5 to proceed against the finalized-segment contract and build no special cases around it. Reassess at the end of Slice 5, and only if it has shown real impact on meeting intelligence, evidence linking, or transcript correctness. Pinned meanwhile by `tests/unit/test_l28_orphaned_final_word.py`, a characterization test that fails the day the shape changes | Found 2026-09-08 in the first real fixture, and invisible to the WER that passed alongside it: the words are all correct and in order, so concatenated text scores 1.43% while the *segmentation* is wrong 27% of the time. **What the numbers prove:** the acoustic gap before each orphan is 160-560 ms, less than half the 1 200 ms threshold, so no silence in the recording can account for a single one of these closes — `on_tick` fired on silence that was never spoken. **What is inferred and not yet observed:** that `transcribed_offset_ms` — frames processed, minus the 500 ms configured delay — drifted past the last emitted word because the model withholds a sentence's final word while it settles the punctuation. That fits every case and fits nothing else obvious, but no log was captured showing the offset and the emission side by side, so it is a cause that fits rather than a cause that was seen. **Confirm it before fixing it:** log `transcribed_offset_ms` against the last word's `end_ms` at each tick on a re-run, which the §12 procedure can produce. Consequences are downstream, not cosmetic — segments are the unit of persistence (ADR-05), of speaker attribution, and of Slice 5's evidence links, and a 160 ms segment holding `tous.` is a poor citation. Not fixed here: the fix is a segmenter or adapter change, which is Slice 4 code work rather than the documentation this pass was asked for. Three candidate directions, none measured: gate the silence tick on emission lag rather than processed frames; have `MlxBackend` report a `transcribed_offset_ms` that accounts for its own withholding; or raise the silence threshold, which A-12's finding already says cannot separate the distributions on its own | **Before the transcript is used for anything.** It is the first thing Slice 5 will trip over, and it should be fixed with a regression test built from this fixture's word timings, the way §9.3 was retuned from B1's |
| L-29 | The `capture` → `gateway_recv` latency hop is meaningless — p95 reads ≈ 3.2×10⁹ ms | Clock domains, not a slow pipeline. The browser stamps `capture_ms` with `Date.now()` (Unix epoch) and the server subtracts a `time.monotonic()` reading (arbitrary origin), so the difference is the distance between two unrelated zeros. Every other hop is server-side at both ends and is sound, which is why the total that matters — gateway → broadcast, 1 343.46 ms p95 — is trustworthy. Harmless to transcription; actively misleading in a latency table, which is why it is named here rather than left for the next reader to rediscover | Whenever client-side latency genuinely needs measuring. The fix is a handshake offset or a server-stamped arrival time, not a bigger number |
| L-30 | ~~`backend/uv.lock` is missing the `mlx` extra~~ **CLOSED 2026-09-08.** Slice 5 added an `openai` extra, which was the trigger the entry named, so the lock was regenerated with `uv lock` and now carries all three extras. `uv run` no longer rewrites it | `pyproject.toml` gained an `mlx` extra in Slice 4 (ADR-13 consequence 5, correctly marked `sys_platform == 'darwin' and platform_machine == 'arm64'`), but the lock committed alongside it was never re-resolved: it contains no `mlx`, `mlx-metal` or `moshi-mlx` entry. uv resolves universally, so the fix adds all 27 of them with their darwin markers intact and changes nothing that installs on Linux. Reproduced here on 2026-09-08 — a bare `uv run python -c pass` is enough. Deliberately **not** committed in rev 12, which is a documentation pass; a 464-line lock diff does not belong in it, and whoever regenerates it should be the person who can then run the suite on both platforms | Next time anyone touches `backend/pyproject.toml`. One command: `cd backend && uv lock`, then commit the result on its own |
| L-31 | ~~No real LLM call has ever been made~~ **HALF CLOSED 2026-09-08.** The provider works end to end; its *numbers* are unmeasured | Aymen ran Slice 5 against the real OpenAI provider and reported it working. That closes the half a fake transport could never answer: the request body is accepted, `gpt-4o-mini` honours the strict schema on real French, and the outputs are usable. It does **not** produce the three numbers the gate asks for — ten meetings, A-6's schema-rejection rate split by reason, and cost per meeting — because those are counts over repeated runs and no count was reported. Recorded as ✅ M1 + MLX for *function*, ⚠ for *rate and cost* | The ten-meeting run, whenever it happens. §12 says what to send back and why each number matters |
| L-32 | ~~The Playwright specs were not re-run against the new review page~~ **CLOSED 2026-09-08.** Aymen ran both specs — host lifecycle through the review page, and two participants sharing one attributed transcript — and both pass against the rewritten page, the health banner and the search box | Slice 5 changed `ReviewPage.tsx` substantially — evidence buttons, audio playback, a cited-segment highlight — and the two browser specs are carried forward from rev 9 unexecuted. The unit tests cover the logic those buttons call, but nothing has clicked one. `npm run test:e2e` needs a running backend and a browser, and this environment has neither reliably | Closed. The equivalent gap now is that no browser spec covers a *degraded* dependency — the banner's failure states are unit-tested only |
| L-33 | Transcript search is meeting-scoped, linear, and not `ILIKE` | Three things, one decision. **Accent-insensitive**: §6 says "ILIKE for now", but PostgreSQL's `ILIKE` is accent-sensitive and this is a French-first product — someone typing `reunion` would find nothing in a transcript saying `réunion`, which is a trust failure in a feature whose job is finding what was said. `CREATE EXTENSION unaccent` was the alternative and needs privileges a local `docker compose` may not grant, which is a poor trade in a phase whose point is that the local path works. **In Python, not SQL**: matching happens after the fetch, which costs nothing extra because rendering the transcript already loads every segment. **Meeting-scoped**: cross-meeting search is not FR-10 and would need PostgreSQL full-text | A meeting long enough for linear matching to be felt (an hour is ~930 segments), or the day cross-meeting search is actually asked for. The deviation is recorded on `transcript/search.py` itself, not only here |
| L-34 | The lifecycle chain has an automated walk and a manual one, and they are not the same walk | `test_full_lifecycle.py` walks create → review in one test, but on `MeasuredRecognizer` and `FakeLLMProvider` — ✅ **fake**. Aymen walked the same chain on 2026-09-08 against real MLX Kyutai and real `gpt-4o-mini` and reported it working end to end — ✅ **M1 + MLX**, but by hand, with no artefact beyond that report. So the chain is *tested* without a model and *demonstrated* with one, and neither half is the other: a passing demo is not evidence (D-03), and a fake's timing is not a model's compute. Accepted because the alternative needs Apple silicon in the test runner, which is L-18 and L-27 rather than anything this test could fix | A CUDA host makes the real path runnable somewhere other than one laptop (Phase B), or someone records a second measured fixture. Until then, read the two halves together and neither alone |
| L-35 | ~~The readiness verdict had no consumer but the banner~~ **FOUND AND CLOSED 2026-09-09.** With the ASR runtime down the app said **Service indisponible** and left **Nouvelle réunion** clickable | Found by Aymen by hand on M1, not by any test — and it could not have been found by the tests that existed. `bannerFor` computed `canStartMeeting` correctly and `status.test.ts` asserted it six times; **nothing consumed it.** `HealthBanner` polled `/readyz` privately and rendered only the sentence, so `MeetingList` never saw the verdict and let a host start a meeting that could not transcribe. The unit tests were green throughout, because the two halves lived in different components and only one had a consumer. Fixed by moving the poll into a `ReadinessProvider` both read, so the banner and the button cannot disagree, plus `meetingCreationBlocked` as the single copy of the rule | Closed. `e2e/degraded.spec.ts` (6) holds it: against the pre-fix code 4 of its 6 tests fail. The **class** of bug is not closed — see the join path in §12, which has the same shape and is deliberately not fixed here |
| L-36 | ~~Every documented way of getting a host token produced an invalid one~~ **FOUND AND CLOSED 2026-09-09** | `uv run python -m mosaique.app.seed | tail -1` appeared in nine places — `CLAUDE.md`, `README.md`, §12 three times, all three browser specs, and `tools/replay/__main__.py`'s own docstring. The seed's last line is `host_token:      eyJ...`, label and padding included, and every consumer sends it verbatim as a bearer token: **401**, measured here against the running server, where the trimmed token gives 200. The replay harness has the same flaw — `f"Bearer {token}"` with no trim. This is a plausible part of why a browser-level gap survived to be found by hand: the documented path to running the browser specs does not work. **No claim is made about how Aymen's 2026-09-08 run got a working token** — only that the written command does not produce one | Closed by changing the nine call sites to `awk '/^host_token:/{print $2}'`. **Not** closed by changing what the seed prints: reshaping its output is a backend decision, and whether the last line should just be the token is the maintainer's call |
| L-17 | `frontend/node_modules/` is tracked in git (4191 files) | Pre-existing; `.gitignore` covers new files but the old entries are still indexed, so an `npm install` dirties the tree. `__pycache__` was untracked on 2026-09-06 — 38 `.pyc` files, unambiguously build output, and they re-dirtied on every test run. `node_modules` is left alone: untracking it changes how a fresh checkout is bootstrapped, which is a call to make on its own | A deliberate decision about how dependencies are vendored |

---

## 11. Changelog

| Date | Change |
|---|---|
| 2026-09-09 | **rev 21. Slice 6R specified — single-user review hardening. Documentation only; nothing built.** Aymen validated PR #14 on the M1 (frontend 79, backend `382 passed, 1 deselected`, typecheck, build, all 8 browser specs, plus manual real-backend testing) and then set the next direction: *"before moving on to the two users and serving the ASR model on a CUDA runtime, we first need to prioritize the single user experience."* **The design principle is his and it is a presentation rule, not a storage one:** preserve the raw segment and word evidence internally, present a human-readable transcript by default — auditability without making every reader parse a stream of model events. ADR-05 is untouched. The concrete failure it names is measurable: `ReviewPage` renders one `<p>` per segment with the speaker repeated on each, segments close on 1 200 ms of silence (§9.3), so an hour of French is ~**930 labelled lines**, 8 in 30 of them a single orphaned word (L-28). **Two modes, both kept**: the live view keeps word-by-word interim rendering because making latency and transcription activity visible is its job, and the review view gets paragraphs grouped by speaker and pause. **The honest part of the specification is that two of the eight priority items are already built**: clickable citations that seek audio (FR-11) and search highlighting (FR-10) both work — and they are in the slice as **regression constraints**, because grouping segments into paragraphs is precisely what breaks them: scroll targets are keyed to per-segment `<p>` nodes and highlight spans index into a single segment's text, not a joined paragraph. Recording them as new work would have been the easy way to write this and would have been false. **Q9 is answered** — transcript corrections move from *out of scope*, a default standing since 2026-09-03, to *in scope, additive only*. Recorded as a dated decision rather than absorbed silently. The constraint follows from the design principle: raw ASR text and word timings are never overwritten, a correction is stored alongside with authorship and a timestamp, and the original stays retrievable — destructive editing would make L-28, the 1.43% WER and every `[measure]` row unfalsifiable after the fact. **Left open on purpose, to be decided inside the slice:** whether correcting a cited segment should invalidate or re-run the intelligence quoting it, which is a paid LLM call and a product decision, so it is not automatic. **Also explicitly outside:** gating the *join* path on readiness — the L-35 sibling, same bug shape, but refusing a participant who already holds an invite is its own product call. **Sequencing:** 6R goes before 6B and 6C, and 6A's last item — the §15 metrics — is deliberately moved behind it, so 6A closes *after* 6R. The plan's critical-path diagram is written to show that interleaving rather than tidied into a false ordering. `docs/IMPLEMENTATION_PLAN.md` goes to v1.4. **No code changed in this revision.** |
| 2026-09-09 | **rev 20. Degraded-state UX — and the bug a person found that the tests could not.** §12 called this item "the one most likely to find a real bug". It was, and the bug arrived before the test: Aymen put each dependency down on his M1 by hand and found that with the ASR runtime unavailable the app showed **Service indisponible**, named `asr_runtime: unknown` in the technical detail — and left **Nouvelle réunion** clickable. A host could start a meeting that could not transcribe, having just been told it could not transcribe. **The reason no test caught it is the interesting part.** `bannerFor` computed `canStartMeeting` correctly and `status.test.ts` asserted it six times; the value simply had **no consumer**. `HealthBanner` owned the only poll, rendered the sentence, and kept the verdict; `MeetingList` never saw it. Every unit test was green because both halves were individually right and nothing tested the join between them — the same shape as rev 19's lifecycle gap, one layer up. Fixed by making readiness shared rather than private: a `ReadinessProvider` owns the single poll, `HealthBanner` and `MeetingList` both read it, and `meetingCreationBlocked` is the one copy of the rule — a second poll in `MeetingList` would have re-created the same class of bug, a banner and a button disagreeing, just harder to see. It handles a third state the banner never needed: `undefined`, the first check still in flight, which must **not** block, or the button is dead for the first half second of every page load. **The scope was held deliberately.** Only creation is blocked; `JoinPage` has the identical shape and is knowingly left, because refusing a participant who already holds an invite is a product call and not a wiring one — recorded in §12 so the next person decides it rather than inherits it. `e2e/degraded.spec.ts` is the regression: six specs covering ASR down, database down, LLM-only down, an unanswered `/readyz`, a healthy control, and recovery re-enabling the button without a reload. **Checked against the pre-fix code rather than assumed load-bearing: 4 of the 6 fail there, and the 2 that pass are exactly the two describing behaviour that was already correct.** `/readyz` is stubbed in the browser and everything else is the real app against the real backend — this asserts the UI contract given a payload, not that the backend detects a downed dependency, which `test_health_probes.py` (11) and `test_health_endpoints.py` (10) already cover and which would need Apple silicon to provoke for real. **A second bug fell out of running it: L-36.** `uv run python -m mosaique.app.seed | tail -1` — in nine places including `CLAUDE.md`, `README.md`, §12 three times, all three browser specs and `tools/replay/__main__.py` — returns `host_token:      eyJ...` with the label attached, and every consumer sends it verbatim as a bearer token. Measured here: 401 with the documented command, 200 with the token trimmed. The replay harness has the same flaw. That the documented way to run the browser specs does not work is a plausible part of why a browser-level gap survived to be found by hand; no claim is made about how the 2026-09-08 run got a working token. Fixed at the nine call sites, *not* by reshaping what the seed prints, which is a backend decision and the maintainer's. Frontend 72 -> 79 unit, browser specs 2 -> 8 and all 8 re-run green here (the pre-existing two included, since `App.tsx` and `MeetingList.tsx` both changed). Backend untouched but re-run: ruff, ruff format, mypy strict (97 files) all clean. **Slice 6A now has one item left**, the §15 metrics. One number from the validation report is recorded rather than smoothed: it gives the backend regression suite as `380 passed, 1 deselected`, and this sandbox measures `382 passed, 1 deselected` both before and after rev 20 — consistent with that run having been made on a checkout predating the rev 19 merge, since 382 - 380 is exactly the two lifecycle tests. Worth a re-run on the M1 to confirm, and not worth guessing about. |
| 2026-09-09 | **rev 19. Slice 6A: the full-lifecycle test. One walk, and what it refuses to claim.** Seven steps each had a passing test; nothing had a test that they *compose*. `tests/integration/test_full_lifecycle.py` walks create → join → speak → end → finalize → summarize → review as one test and asserts each hand-off rather than only the ends: JOINABLE → LIVE happening at the first accepted audio and not at create, interim **and** final segments broadcast live and attributed to the speaker, `asr_version` written on end, one AudioSession with frames counted, exactly one job enqueued, `meeting.outputs.ready` reaching a socket that is still open — the socket is deliberately held across the end and the summarize, because that is what a participant's browser is actually doing — and then the review leg: every segment the summarizer cited resolved the way `evidence.ts` resolves it (segment → recording → epoch → byte offset), a 206 Range at that offset returning the same bytes as the whole body, and the moment found again by an accent-stripped search. **`MeasuredRecognizer` over a `LocalAudioStore`**, both on purpose: the scripted fake's metronome would give segment boundaries no real run produces, and the null store would make the last leg of FR-11 unfalsifiable — a citation resolving to an offset nobody can check. A second test runs two meetings back to back through one process and asserts neither carries the other's segments or timeline anchor, because Slice 6A's bar is *repeatedly*, not once. **Checked for being load-bearing rather than assumed to be**: with `audio_session_id` dropped at the insert it fails on the citation join, and with `fold()` made accent-sensitive it fails on the search — both mutations reverted. Two things the first draft got wrong and are worth passing on: a meeting is created `JOINABLE`, not `LIVE`; and picking the *first* accented word to search for picks `à`, which is below `MIN_QUERY_LENGTH`, so the route answers with the whole transcript and the assertion passes while proving nothing — it now takes the longest accented word and fails loudly if none is long enough. Backend 380 -> 382; ruff, ruff format, mypy strict (97 files), frontend `72 passed`, `npm run build` and the accelerated hour all green; `openapi.json` regenerated with no drift. **What this does not claim, recorded as L-34:** the walk is ✅ **fake** — no weights, no provider. Aymen walked the same chain on real MLX + `gpt-4o-mini` on 2026-09-08, but by hand and with no artefact, so the chain is tested without a model and demonstrated with one, and neither half is the other. Also unclaimed: the second meeting is *sequential*, so it says nothing about A-15, which is about concurrent pumps. No source file changed — this revision is a test and this document. |
| 2026-09-09 | **rev 18. Handoff. Local validation on M1 recorded; nothing built.** Aymen pulled the branch to his own machine and ran everything: backend **`380 passed, 1 deselected`** — matching this sandbox exactly, which is the cross-check that matters most given there is no CI (L-18) — the measured-timing and reconnect/idle/health subsets green, frontend `72 passed`, PostgreSQL healthy in Docker, the frontend serving on `127.0.0.1:5173`, and **`/readyz` reporting ready with MLX weights and the database healthy**. That last one is the first time the readiness endpoint has been exercised against real weights rather than a fake backend, and it is what moves the health work from ✅ fake to ✅ M1 + MLX. One number disagreed and is recorded rather than smoothed over: the measured-timing file collects **11** tests here and was reported as 10, most likely a `-k` filter difference; the file's own count is the verifiable one. Then the handoff itself: `CLAUDE.md`'s current-state section was rewritten for a cold start — where the project is, the three phases, the next three tasks with what "done" means for each, a table of decisions that must not be re-litigated (L-28 deferred, Q2's residency half open, L-33's search deviation deliberate), and where each claim was verified. §12 gained a **START HERE** block naming those three tasks concretely. Also corrected: this file's header said rev 14 while §11 carried rows through rev 17 — changelog rows had been appended without bumping the header. §11 was always the authoritative history; the header now agrees with it. **No code changed in this revision.** |
| 2026-09-08 | **rev 17. Slice 6A task 1 validated on real hardware; A-14 largely answered without any.** Aymen ran the full stack on M1: both Playwright specs pass against the rewritten review page, the health banner and the search box — **L-32 closes** — and a manual end-to-end meeting on real MLX Kyutai plus OpenAI `gpt-4o-mini` went the whole way: model loaded, readiness checks green, live French transcript, persisted on end, summary generated, actions with timestamps, evidence rendered. Health endpoints move from ✅ fake to ✅ fake + ✅ M1 + MLX. **Then the interesting half.** Seven things remained unmeasured, and most of them looked like they needed Apple silicon. They did not all: the ones that are really about *how the runtime reacts to a model's timing* can be answered from data already in the repository. `docs/mosaique-b1-main/b1-tokens.jsonl` is a token-by-token log of a real MLX run — 162 tokens, each with the stream position it was emitted at — and `sum(pieces) == len(tokens)` pairs them exactly onto the 92 assembled words, giving **the stream offset at which a real model actually produced each word**. `MeasuredRecognizer` replays that. The runtime now meets word gaps of **p50 320 ms, p95 1 280 ms, max 24 080 ms** instead of a metronome, replayed in stream time so it stays speed-invariant (ADR-11). Under it: a meeting transcribes in order, the fixture's 24-second hole does **not** trigger an idle close — that path is keyed to frames, not events, and now there is a test saying so — a reconnect landing mid-burst neither duplicates nor loses segments, and ending while the model still owes ~500 ms of words flushes the tail rather than dropping it. A-14 goes from *partially answered* to *largely answered*. One correction caught in review of my own numbers: the first draft quoted **token**-level gaps (p50 80 ms) in a docstring describing a **word**-level emitter; the fixture is burstier at the token layer, but the runtime never sees tokens, so the claim was wrong at the level it was made. Backend 365 -> 380. **Still needing the Mac, unchanged and not claimed:** real-time factor, first-word and final-segment latency, memory growth, and long-run MLX stability. |
| 2026-09-08 | **rev 16. Slice 6A: transcript search (FR-10), and a deliberate deviation from the spec.** §6 says `?q=` should be "ILIKE for now". It is not, and the reason is the product: PostgreSQL's `ILIKE` is accent-sensitive, so a French speaker typing `reunion` would find nothing in a transcript that says `réunion` — a trust failure in the one feature whose job is finding what was said, and people skip accents constantly. `CREATE EXTENSION unaccent` was the obvious alternative and wants privileges a local `docker compose` or a hosted database may not grant, which is a poor trade during a phase whose whole point is that the local path works. So matching happens in Python, after the fetch — which costs nothing extra, because rendering a transcript already loads every segment. **The subtle part is the folding.** NFD splits `é` into two code points, so stripping combining marks would shorten the string and slide every later offset; the fold is therefore per character, one in and one out, and a test asserts `text[start:end] == "budget"` on a sentence with an accent *before* the match — an assertion that only checked "a span was found" would have passed on broken arithmetic. Offsets are returned by the server rather than recomputed in the browser, because duplicating accent-folding in two languages is two implementations that drift and a highlight that lands a character off on every `é`. The client is defensive anyway: spans that arrive reversed, negative, out of range or overlapping are dropped, and a test asserts the rendered parts always rejoin to the original text — a scrambled sentence would be worse than an unhighlighted one. The review page debounces and discards any response whose echoed `query` is not what is still in the box, so a slow answer for `bud` cannot land after a fast one for `budget`. Backend 343 -> 365, frontend 60 -> 72. The deviation is **L-33**, recorded with its two other consequences: search is meeting-scoped, and it is linear. |
| 2026-09-08 | **rev 15. Slice 6A begins: health endpoints that say *which* dependency broke.** First Phase A task, chosen because Phase A means running meetings repeatedly on a laptop and the cost of a bad run is mostly the time spent guessing why. `/readyz` and `/health/deps` now exist alongside `/livez`, and the three answer deliberately different questions: is the process up, could this instance take a meeting, and what is each dependency doing. Per §15 the **LLM provider is listed but does not gate readiness** — a meeting records, transcribes and persists without it and only the summary waits, so failing readiness there would refuse meetings that would have worked; the flag is carried in the response as data rather than as an `if` in the route, so a reader can see why. The ASR probe asks the recognizer **through the seam**: `RecognizerReadiness` is a new method on the `StreamingRecognizer` Protocol with no default, following the L-25 lesson that a capability read with `getattr(..., default)` gets the default silently — and here the tempting default, "ready", is the one that turns a broken runtime into a green health check. It has **three** states, not two: `unknown` exists because "I have not checked" is a real answer, and `/readyz` treats it as not-ready. That is what keeps `moshi_server` honest — it reports `unknown` rather than vouching for a server nobody has ever reached (L-27), so the gap stays visible until Slice 6B implements a real probe. Probes run concurrently with a 3 s timeout each and are individually guarded, because a health endpoint that hangs or 500s during an outage is worse than none. The frontend gained a banner that renders **only when something is wrong**, leads with what blocks the meeting rather than what delays the summary, and hides the technical detail behind a toggle. Backend 315 -> 343, frontend 49 -> 60; `ruff`, `mypy`, `npm run build` clean, OpenAPI regenerated (10 paths). Not claimed: the banner has never been seen in a browser (L-32), and nothing here has met a real MLX runtime — `readiness()` on the MLX path is ⚠, exercised only through a fake backend. |
| 2026-09-08 | **rev 14. Re-sequenced into Phases A/B/C; Slice 5 confirmed working against the real provider.** Aymen ran Slice 5 end to end with the real OpenAI provider and reported it working, which closes the half of L-31 a fake transport could never answer: the body is accepted, `gpt-4o-mini` honours the strict schema on real French, and the outputs are usable. **The gate's numbers are still unmeasured** — ten meetings, A-6's rejection rate split by reason, cost per meeting — and are recorded as such rather than rounded up from one good run. Then the sequencing change: the product is proven end to end for one participant on hardware that exists, and four participants are gated on hardware that does not, so the remaining work splits into **Phase A** (harden the single-user product on M1 + MLX — current), **Phase B** (deploy `moshi-server` on a dedicated NVIDIA host and measure the production serving path), **Phase C** (four participants). **Slice 6 was split, not reduced**: the plan now carries a table mapping every original Slice 6 item and every original exit-gate clause into exactly one of 6A / 6B / 6C, so nothing can be quietly dropped. Consequences here: **L-26 stops being an immediate blocker** — MLX serving one stream is sufficient for Phase A and disqualifying for Phase C, both of which were always true; what changed is which one is next. A-3 and A-16 are relabelled from open-ended spikes to Phase B work. §0 gains a **validation-environment vocabulary** — ✅ M1 + MLX, ✅ fake, ⚠ implemented-not-validated, ❌ needs NVIDIA, ❌ needs cross-network — because `VERIFIED` alone stopped being precise once two runtimes existed and a number measured on MLX does not describe CUDA. The rule it exists to enforce: **the production GPU serving path is not marked verified until it has served a meeting.** L-28 remains deferred; the re-sequencing does not touch it. No code changed in this revision. |
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

### START HERE — Slice 6R, then 6A's last item (2026-09-09)

**The current slice is 6R — single-user review hardening.** It is specified in
`docs/IMPLEMENTATION_PLAN.md` v1.4 and **not yet implemented**; read that section
before starting, because it names what already works and must not regress.

Slice 6A is five of six done. Its last item — the §15 metrics, item 1 below — is
**deliberately sequenced after 6R**, at Aymen's direction: a readable transcript
is worth more to a single user than a counter. So the order is 6R, then the
metrics, then 6B.

### Slice 6R in one paragraph

`ReviewPage` renders one `<p>` per segment with the speaker's name repeated on
every one. Segments close on 1 200 ms of silence, so an hour of French is ~930
labelled lines and 8 in 30 are a single orphaned word (L-28). The fix is
presentational, not structural: **preserve the raw segment and word evidence
internally, present a human-readable transcript by default.** ADR-05 does not
change. The live view keeps its word-by-word interim rendering on purpose — that
is the debugging and auditing surface. Seven items, two of which (clickable
citations, search highlighting) already work and are regression constraints
because grouping is what would break them. Q9 is answered and corrections are
**additive** — raw ASR text is never overwritten.

### The rest of Phase A

The two finished 6A items below are kept, struck through, with what they
produced — including the bug item 2 found, which is the argument for doing the
remaining work properly rather than quickly.

**1. The remaining §15 metrics, with a stated reason each.**
The spec lists them (`meetings_active`, `audio_frames_received_total`,
`transcript_first_word_latency_ms`, and about twenty more). `/livez`, `/readyz`
and `/health/deps` already exist; this is the counters-and-histograms half.
*The "stated reason each" is the point* — the plan asks for it because a metric
nobody can name a use for is a metric nobody reads. Done when each emitted metric
has a one-line reason and a test that it moves when the thing it measures
happens.

**2. ~~Degraded-state UX.~~ DONE 2026-09-09 — `e2e/degraded.spec.ts` (6).**
It was called "the one most likely to find a real bug" and it was. Aymen found
the bug by hand first (L-35): the banner said *Service indisponible* with the ASR
runtime down and **Nouvelle réunion** stayed clickable, because `canStartMeeting`
was computed, asserted six times in `status.test.ts`, and **consumed by nobody**.
The poll now lives in `ReadinessProvider` and the banner and the button read the
same copy. Against the pre-fix code 4 of the spec's 6 tests fail, and the 2 that
pass are exactly the two describing behaviour that was already right.

**What this deliberately did not do, and the next person should decide.** Only
*creation* is blocked. `JoinPage` has the same shape — a participant can still
join a meeting whose transcription engine is down, speak, and have the audio
stored with nothing to read afterwards. That is arguably worse than the bug just
fixed, and it is a product call rather than a wiring one: refusing a participant
who already has an invite, possibly mid-meeting, is a different decision from
greying out a host's create button. It is **not** in this slice. Do not fix it
without asking.

**3. ~~The full-lifecycle test.~~ DONE 2026-09-09 —
`tests/integration/test_full_lifecycle.py`.** One test walks create → join →
speak → end → finalize → summarize → review and asserts the transcript and the
outputs at the end; a second runs two meetings through one process and checks
neither inherits the other's segments or timeline anchor. `MeasuredRecognizer`
over a `LocalAudioStore`, so segment boundaries carry a real MLX run's emission
timing and a citation's byte offset can actually be fetched. **✅ fake only** —
see L-34 for what that does and does not say. Two things worth knowing if you
extend it: a query below `MIN_QUERY_LENGTH` is answered with the *whole*
transcript, so an accent-insensitivity assertion built on a one-letter word like
`à` passes while proving nothing; and a meeting is created `JOINABLE`, not
`LIVE` — the transition belongs to the first accepted audio.

**Do not attempt in a sandbox** — these need Aymen's M1 and are his to run:
real-time factor, first-word and final-segment latency, memory growth, long-run
MLX stability. One long `tools/replay run … --speed 1` against MLX yields the
first three from the report it already writes.

**Before you change anything, read `CLAUDE.md` "Decisions already made".** L-28
is deferred by decision, Q2's residency half is open, and the search deviation
(L-33) is deliberate. Re-opening any of them unprompted wastes a session.

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
export MOSAIQUE_HOST_TOKEN="$(cd ../backend && uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')"
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
  --host-token "$(uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')" \
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
  --host-token "$(uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')" --speed 10
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

### What to pick up next — Phase A (2026-09-08 re-sequencing)

**The current track is Slice 6A: make the single-user product reliable on
M1 + MLX.** Not "it works once" — it works repeatedly, and when it does not, you
can see which dependency broke. Everything below runs on a laptop.

1. **`/readyz` and `/health/deps`, per dependency.** First, because it is what
   tells you *which* thing is broken when a local run fails — database, ASR
   runtime, or LLM provider — and Phase A means running meetings over and over.
   `/livez` already exists and only says the process is up.
2. **Transcript search (FR-10).** The last unbuilt functional requirement a
   single participant can exercise.
3. **A long single-user run against the real MLX runtime.** The accelerated hour
   exists but runs on the *fake*; A-9's memory question and A-14's thresholds
   have never met real jitter for more than 116 seconds.
4. ~~**A full-lifecycle test**~~ — **DONE 2026-09-09**,
   `tests/integration/test_full_lifecycle.py`, ✅ fake. Create, join, speak, end,
   finalize, summarize, review as one walk, plus a second meeting through the
   same process. L-34 records what a fake-only walk does not cover.
5. **Slice 5's numbers**, whenever ten meetings happen: A-6's rejection rate
   split by reason, and cost per meeting. Phase A work now, not a blocker.
6. **Degraded-state UX** — ~~for each dependency that can be down~~ **DONE
   2026-09-09** for the create path, `e2e/degraded.spec.ts`; the join path is
   knowingly left (see the START HERE note). The remaining **§15 metrics with a
   stated reason each** are still open and are now the last 6A item.

**Explicitly not now, and not forgotten:** four participants, concurrent
streaming ASR, `moshi-server`, CUDA validation, GPU memory and concurrency
benchmarking, four-participant load testing, dedicated GPU deployment. All of it
is Phase B and Phase C in `docs/IMPLEMENTATION_PLAN.md`, with the original Slice
6 exit gate carried into 6C unchanged. The blocker is a procurement decision, not
an engineering one.

### The older list, still true

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
