# Mosaïque — Final Implementation Blueprint

> **Current amendment — 2026-09-12:** [Two-user voice / Azure ASR architecture](two-user-cloud-architecture.md)
> records the maintainer's new priority and supersedes companion-only D-01/ADR-01,
> the WebRTC exclusion and older single-user-first sequencing where they conflict.
> Direct WebRTC/TURN carries voice; the existing PCM WebSocket and ASR seams remain.
> Work proceeds one slice, one documented PR, review/merge, then the next slice.
> R0 is documentation only; deployment review is pending and no new feature or
> infrastructure is claimed implemented. Historical text below retains its original
> evidence; use the root PROJECT_STATE.md and the R0 sequence for current next work.

**Version:** 1.2 (scope restored)
**Date:** 2026-09-03
**Status:** Reconciliation layer over the Technical Specification. Not a replacement for it.
**Scope:** Smallest viable remote-meeting prototype (PRD Stage 2 → Stage 4), Level 1 maturity.

**Normative source for what is being built now: Technical Specification v0.1.** This blueprint resolves contradictions between the source documents and records decisions the specification left open. Where this blueprint is silent, the specification governs. Future-architecture analysis lives in `mosaique-future-media-plane-options.md` (ADR-12) and is explicitly **non-normative** — it does not change prototype scope, slice order, or spike priority.

---

## 1. Purpose and document hierarchy

Four documents describe this system and they do not agree everywhere. This blueprint reconciles them and states which one wins on each axis.

| Document | Owns | Authority |
|---|---|---|
| Product Requirements Document | Why the product exists, user journeys, functional requirements FR-01…FR-11 | Product intent. Wins on *what the user gets*. |
| `realtime-meeting-product-engineering.md` (skill) | Standing engineering rules, anti-patterns, maturity levels | Wins on *how we build*, except where it gives an illustrative example (see §3.2). |
| System Architecture & Design Blueprint | Component boundaries, dependency direction, replaceability seams | Wins on *which module owns what*. |
| **Technical Specification v0.1** | Prototype scope, wire contracts, schemas, thresholds, failure matrix, implementation sequence | **Normative for what is built now.** Amended only where §6 says so. |
| This blueprint | Reconciliation of contradictions, decisions the spec left open | Wins only where the source documents conflict with each other. |
| `mosaique-future-media-plane-options.md` (ADR-12) | Media-plane options for later | **Non-normative. Governs nothing.** |
| `PROJECT_STATE.md` | What actually exists and is verified | Wins on *current reality*. Never describes intent. |
| `IMPLEMENTATION_PLAN.md` | Order of work | Wins on *what to build next*. |

Rule: when this blueprint amends a source document, the amendment is recorded in §6 with the section it replaces. Source documents are not silently edited.

---

## 2. Locked decisions

### 2.1 D-01 — Prototype ingress and media scope (decided 2026-09-03, resolves Q1 for the prototype)

For the prototype, Mosaïque does **not** carry voice between participants and does **not** integrate with any external conferencing platform. Each participant's browser captures their own microphone and streams it to the backend over WebSocket. Every participant sees the same merged live transcript.

This is the Technical Specification's design, unchanged. ADR-01 (WebSocket + raw PCM, no LiveKit) stands.

| # | Consequence | Where it lands |
|---|---|---|
| C1 | No WebRTC/LiveKit media routing, no SFU, no platform integration. | Topology unchanged |
| C2 | Every participant runs Mosaïque. Acceptable for the prototype: participants are known and consenting. | Operating condition, not a defect |
| C3 | Browser echo cancellation is enabled; far-end leakage through loudspeakers is a known limit. Headphones are recommended in the join UI. | Slice 1 UI |
| C4 | Participants join at different times and may leave and return. The timeline cannot assume a common start. | D-02 |
| C5 | The prototype is for internal and consenting-participant use. It is not pitched to customers whose guests cannot be asked to open it. | Limitation L-1 |

**Explicitly not decided by D-01:** where audio comes from in the eventual product. That is an open product question, analysed in ADR-12 and deliberately left open. It does not block anything in the prototype, because D-04 makes the ingress replaceable.

### 2.1a D-04 — Minimal ingress seam (decided 2026-09-03)

The meeting runtime, ASR adapter, transcript engine, persistence, and intelligence layers must not know where audio came from. One small boundary buys that:

```python
class MeetingIngress(Protocol):
    async def start(self, meeting: MeetingRef) -> None: ...
    def events(self) -> AsyncIterator[IngressEvent]: ...   # ParticipantJoined | ParticipantLeft
                                                            # | AudioFrame | IngressError
    async def stop(self) -> None: ...

@dataclass(frozen=True)
class AudioFrame:
    participant_id: ULID
    audio_session_id: ULID
    seq: int
    pcm: bytes          # canonical format, §8.1
```

**One implementation now:** `BrowserWebSocketIngress`, exactly the gateway the specification describes. The seam adds a Protocol and a module boundary, nothing else.

The rule that earns its keep, enforced by an architectural test (per the design blueprint §27): **nothing downstream of this seam imports WebSocket, FastAPI, or transport types.** The same test that lets `FakeRecognizer` stand in for Kyutai lets a future ingress stand in for the browser.

**Deliberately not built:** capability negotiation, platform identity mapping, per-source consent modes, multi-ingress meetings. Those are hypothetical change points, and the engineering skill §2.3 is explicit — abstract real change points, not hypothetical ones. A future ingress adds them when it exists.

**Schema:** one column. `Meeting.source_kind ENUM(direct, ...)`, with `direct` the only value. Cheap now, awkward to add later, same reasoning as ADR-08. The other columns proposed in an earlier revision — `external_meeting_ref`, `source_capabilities`, `consent_mode`, `external_participant_id`, `identity_source`, `ingress_kind` — are **withdrawn** as speculative and move to ADR-12 as future work.

**R-11 stands as originally written:** `AudioSession.sample_rate` remains a constant-valued column. The prototype captures at 24 kHz; no resampling branch exists. `speech/audio/` stays "only if ever needed", as the specification says.

### 2.1b D-05 — Kyutai facts confirmed, and one latency technique adopted (2026-09-03)

Verification against current Kyutai documentation **confirms** the assumptions in specification §8.1 and §9.2. This reduces risk; it changes no scope.

| Specification assumption | Status |
|---|---|
| 24 kHz input, 80 ms frames (12.5 Hz frame rate) via the Mimi codec | Confirmed |
| ~0.5 s delay for `stt-1b-en_fr` | Confirmed |
| Word-level timestamps | Confirmed |
| Semantic VAD / end-of-turn signal | Confirmed |
| `moshi-server` (Rust) with WebSocket streaming, config for `stt-1b-en_fr` | Confirmed |
| Concurrency headroom | Better than assumed — roughly 400 real-time streams on an H100. Four streams is not a capacity question. |
| Licensing | Weights CC-BY-4.0 |

**Adopted technique — the flush trick.** The server processes audio faster than real time (roughly 4×). On end-of-speech, rather than waiting the full model delay before closing a segment, flush the already-sent audio and let the server catch up — turning a ~500 ms wait into roughly 125 ms.

This amends specification §9.3 (segmenter) and §11 step 3 (finalization drain): `ASRSession.flush()` should trigger accelerated processing where the runtime supports it, not merely push silence. It improves final-segment latency, which X-4 identified as the weaker of the two budgets, and it makes the 20 s finalization drain deadline generous rather than tight.

**Still to verify in Spike B:** whether `moshi-server` serves concurrent independent streams cleanly (A-3), and whether emitted text is ever retracted (A-2, second half).

### 2.2 D-02 — Meeting timeline is derived from audio frames, never from client clocks

This decision is new; none of the four documents settles it, and every cross-participant feature depends on it.

```text
meeting.started_at        = server time at JOINABLE → LIVE
AudioSession.epoch_ms     = server receive time of the session's first accepted frame
                            − meeting.started_at
segment.start_ms          = AudioSession.epoch_ms + asr_stream_offset_ms
asr_stream_offset_ms      = 80 ms × (frames pushed into the ASR session, including
                            silence padding inserted for missing frames)
```

Rules:

- A `seq` gap causes **silence padding of `gap_count × 80 ms` to be pushed into the ASR session and written to the audio file**. This keeps stream offset, file offset, and capture time aligned, and is acoustically correct.
- Client-supplied `capture_ms` is used only for duplicate/gap diagnostics and for detecting pauses. It is never trusted for ordering and never written to a durable timestamp.
- A pause (mute or network stall) of **> 30 s closes the AudioSession**. Resume opens a new AudioSession with a fresh server anchor. This bounds silence padding at ~1.4 MB per pause and reuses machinery already required for reconnects.
- Consequence: `audio_file_byte_offset = session_ms × 48` exactly, so FR-11 timestamp navigation is arithmetic, with no index table.
- Consequence: cross-participant ordering by `start_ms` carries a one-time anchor error of roughly RTT/2 per session (tens of milliseconds), not accumulating clock drift.

Recorded as **ADR-11**.

### 2.3 D-03 — Verification vocabulary

"Done" means a named automated test passes or a number was measured and written down. A working demo is not evidence. `PROJECT_STATE.md` enforces this distinction and is the only place that may claim something works.

---

## 3. Contradictions found, and their resolutions

### 3.1 Between documents

| # | Contradiction | Resolution |
|---|---|---|
| X-1 | PRD §6/§11/§20 read as though participants meet *inside* Mosaïque ("two people can join remotely", "browser establishes a realtime audio connection"). Tech spec ADR-01 and D-01 make it a companion. | Companion wins. PRD amendment A-1. "Join a meeting" means join the Mosaïque transcription session. |
| X-2 | Skill §9 canonical audio example is 16 kHz mono; tech spec §8.1 is 24 kHz. | 24 kHz wins — the skill explicitly marks its example as not universally correct and defers to the model. Conditional on Spike B. |
| X-3 | PRD §13 calls the remote-participant model "the easiest and highest-quality environment". In companion mode that is true only with headphones; on speakerphone every participant's microphone captures every other participant, producing duplicate and misattributed segments. | PRD §13 is amended (A-2): per-stream attribution is reliable **only** under the headphone constraint. Spike A measures the failure mode. |
| X-4 | PRD §18 asks for "sub-second to low-single-digit-second" latency. With a ~0.5 s model delay plus a 700 ms silence threshold, *final* segments land at roughly 1.5–2.5 s. | Two separate budgets, not one: `first_word_latency` p95 ≤ 2.0 s (the perceived-live number) and `segment_final_latency` p95 ≤ 3.5 s. Both **[measure]**. |
| X-5 | Blueprint §14 UML types `Meeting.transcript_version` as a plain int; tech spec §4 makes it NULL until COMPLETED. | Tech spec wins. NULL while live is what makes the unique key on `MeetingOutputs` meaningful. UML is conceptual. |
| X-6 | Blueprint §14 UML gives `Job.meeting_id`; tech spec §4 gives `Job.payload` with no explicit FK. | Both: `meeting_id` as a real FK column (needed for cascade delete and querying) plus `payload` for everything else. |
| X-7 | PRD §19 measures "user correction rate", but PRD §5 scope excludes transcript editing. | Editing is out of scope for the prototype (Q9 default). The metric is deferred, not silently dropped. Recorded in `PROJECT_STATE.md` as DEFERRED. |
| X-8 | PRD §21 Stage 1 (local mic → Kyutai → live transcript) is skipped entirely by the tech spec, which starts at Stage 2. | Stage 1 is not skipped, it is renamed: **Spike B** is PRD Stage 1, run as a de-risking experiment rather than as product work. |
| X-9 | Skill §44 prescribes a largely horizontal build order (domain → transport → ASR → persistence → finalization → intelligence). The requested plan is thin vertical slices. | Vertical slices win. §7 maps every skill §44 step to the slice that delivers it, so nothing is lost. |
| X-10 | Blueprint §22 shows a single deployment; tech spec §2.1 shows four processes. | Not a real conflict: four containers, one host, one Compose file. Stated explicitly to stop the question recurring. |

### 3.2 Internal to the technical specification

| # | Problem | Fix |
|---|---|---|
| X-11 | `DELETE /meetings/{id}` is described in §13.3 but absent from the §6 route list. | Add to the API surface. Lands in Slice 7. |
| X-12 | `MeetingOutputs.status` and `Job.status` both track the same workflow and can diverge. | Collapse: **`Job` owns execution state** (pending/running/failed/succeeded, attempts, backoff). A `MeetingOutputs` row is inserted **only on success**. `GET /outputs` returns 202 plus job state while absent. One writer, no drift. |
| X-13 | §7.1 defines `last_ack_sequence` in `hello`, but nothing consumes it until reconnect exists. | Keep in the protocol schema from Slice 1 (versioned wire format), implement the behavior in Slice 3. |
| X-14 | §9.3 relies on `revision` as a correction mechanism, but the chosen model does not retract text, so revisions only ever grow. | Keep the field and the client rule (a future ASR may retract). Add an invariant test: interim text is append-only within a segment. The reconciler test matrix shrinks accordingly. |
| X-15 | Frame sizes appear as both 3840 and 3849. | Both correct and consistent: 9-byte header + 3840-byte payload = 3849 total. Stated once here to prevent a bug. |

---

## 4. Complexity to remove or defer

The specification is written at Level 2 in places. The prototype is Level 1. These are the cuts.

| # | Item | Decision |
|---|---|---|
| R-1 | `audio.pause` / `audio.resume` control messages | **Defer to Slice 3.** The server already infers idleness from frame absence; D-02 handles the timeline. Keep in the schema, ignore in Slice 1. |
| R-2 | Magic-link host authentication | **Defer to Slice 7.** Slices 0–6 use a pre-provisioned pilot account plus signed session tokens. Auth *boundaries* are built in Slice 1; only the login mechanism is deferred. |
| R-3 | Transcript search (`?q=`) | **Defer to Slice 6.** FR-10's "read" half ships in Slice 1; ILIKE is a two-hour addition later, `tsvector` later still. |
| R-4 | `GET /audio/{session_id}` with Range support | **Defer to Slice 5**, where the review page actually scrubs. |
| R-5 | Separate `processor` process | **Never for the prototype.** In-process asyncio task, module boundary preserved. Split only if job runtime affects API latency. |
| R-6 | S3-compatible object storage | **Defer.** Local volume behind an `AudioStore` interface with one implementation. |
| R-7 | `words JSONB` per segment | **Keep, nullable.** Populate only when the adapter provides word timings for free. FR-11 needs segment-level timing only; word-level enables later highlighting at near-zero cost. Never a blocker. |
| R-8 | Alerting rules | **Defer to Slice 7.** Metrics endpoint from Slice 6; alerts when there is something to page. |
| R-9 | Prometheus metric set (§15, ~25 metrics) | **Slice 1 ships four**: `transcript_first_word_latency_ms`, `audio_frames_received_total`, `audio_frames_rejected_total{reason}`, `meetings_completed_total`. The rest arrive in Slice 6 with a reason each. |
| R-10 | LLM transcript chunking for long meetings | **Defer to Slice 5**, gated on the token-count measurement in Spike D. Prototype asserts on length and fails loudly. |
| R-11 | `AudioSession.sample_rate` column | Keep as a constant-valued column. No logic branches on it in the prototype. |
| R-12 | `organization_id` on every table | **Not a cut.** ADR-08 stands: cheap now, expensive later. |
| R-13 | FAILED / CANCELLED states | **Not a cut.** Trivial to implement, and the recovery path in §11 needs FAILED. |

---

## 5. Assumption register — what must be validated before it is relied on

Every one of these is currently an assumption inherited from a document, not a measured fact. Each has a named spike or slice that resolves it.

These are the prototype's assumptions. Future-architecture risks (N-1…N-7) live in ADR-12 §6 and gate nothing here.

| # | Assumption | If false | Validated by |
|---|---|---|---|
| A-1 | Browser AEC adequately suppresses far-end audio from another application | Prototype meetings need headphones; attribution noisier without them | **Spike A** — informational, does not gate any slice |
| A-2 | Kyutai STT-1B: 24 kHz, 80 ms hop, word timestamps, semantic VAD, **and does not retract emitted text** | §8.1 format and §9.3 segmenter shift | **Mostly confirmed (D-05).** Spike B covers the retraction question only |
| A-3 | `moshi-server` serves concurrent independent streams cleanly | Fall back to in-process PyTorch behind the same adapter interface | **Spike B** |
| A-4 | The available GPU sustains 4 concurrent real-time streams; CPU-only viability | Participant ceiling, queue sizing, hosting cost | **Spike C, reduced to half a day** — vendor figures suggest large headroom (D-05); confirm on our hardware |
| A-5 | A 60-minute 4-person French transcript fits one LLM context window | Chunk-and-merge becomes Slice 5 work, not deferred work | **Spike D** — token-count a synthetic transcript |
| A-6 | An LLM reliably returns valid `evidence_segment_ids` | Evidence linking degrades to a soft warning instead of a hard validation | Slice 5, measure schema-rejection rate |
| A-7 | AudioWorklet 48→24 kHz resampling is cheap and clean on a mid-range laptop | Move resampling server-side (bandwidth doubles) | Slice 1, measure main-thread and worklet CPU |
| A-8 | 12.5 frames/s per participant over WSS survives ordinary home and mobile networks | Larger frames or client-side batching | Slice 2 replay + one real cross-network test |
| A-12 | The flush trick (D-05) is available through the adapter and behaves as documented | Final-segment latency reverts to the model delay; §11 drain deadline unchanged | Slice 4, measure `segment_final_latency` with and without |
| A-9 | Holding an ASR session open for a 30 s reconnect grace does not leak GPU memory | Shorten grace, or tear down and re-open | Slice 3, 60-minute accelerated replay |
| A-10 | French WER on real, overlapping, accented meeting audio is good enough to be useful | Model swap, or fine-tuning becomes a project | Slice 4 smoke test against a real fixture |
| A-11 | "Joining is consent" satisfies French/EU recording and GDPR obligations | Consent flow, DPA, and subprocessor list all change | **Not an engineering question.** Needs counsel before any pilot with real customer data. Flagged, not assumed. |

---

## 6. Amendments to the source documents

| ID | Document | Amendment |
|---|---|---|
| A-1 | PRD §6, §11, §20, §25 | Reframe as companion mode. "Join a meeting" = join the Mosaïque transcription session, not a voice call. |
| A-2 | PRD §13 | Per-stream attribution is reliable only under the headphone constraint; speakerphone in companion mode reduces to the mixed-audio problem. |
| A-3 | PRD §18 | Split the latency target into `first_word` and `segment_final` budgets. |
| A-4 | PRD §19 | "User correction rate" deferred with editing (Q9). |
| A-5 | Tech spec §4 | `Job` gains `meeting_id` FK. `MeetingOutputs` loses `status`; the row exists only on success. |
| A-6 | Tech spec §6 | Add `DELETE /meetings/{id}`. |
| A-7 | Tech spec §7 | Add ADR-11 timeline rules (D-02) to the protocol section: silence padding on `seq` gaps, session close after 30 s idle. |
| A-8 | Tech spec §8.5 | Audio file contains silence padding, so byte offset maps arithmetically to session time. |
| A-9 | Tech spec §15 | Metric set staged across Slice 1 / Slice 6 / Slice 7 per R-9. |
| A-10 | Blueprint §14 | UML is conceptual; the tech spec schema as amended is the implementation. |
| A-11 | Tech spec §3, §9.3, §11 | Add `MeetingIngress` seam (D-04): `realtime/gateway/` implements it; runtime consumes it. Add `Meeting.source_kind`. `flush()` triggers accelerated processing where supported (D-05). |

---

## 7. Skill §44 sequence mapped onto vertical slices

Nothing from the recommended sequence is dropped; it is re-cut so that each slice is demonstrable end to end.

| Skill §44 step | Slice |
|---|---|
| 1. Domain model + meeting state | 0, 1 |
| 2. One authenticated meeting | 1 |
| 3. Browser audio capture | 1 |
| 4. Transport contract | 1 |
| 5. Streaming ASR adapter | 1 (fake) → 4 (Kyutai) |
| 6. Interim/final transcript UI | 1 |
| 7. Durable transcript persistence | 1 |
| 8. Reconnect + failure handling | 3 |
| 9. Meeting finalization | 1 (happy path) → 3 (recovery) |
| 10. Summary / decisions / actions | 1 (fake LLM) → 5 (real) |
| 11. Observability + replay harness | 2 (harness) → 6 (observability) |
| 12. Multi-user / load testing | 2 (two) → 6 (four) |
| 13. Billing / usage accounting | Out of prototype scope; `PROJECT_STATE.md` records it as DEFERRED |
| 14. Production deployment hardening | 7 |

---

## 8. Open questions still blocking work

Q1 is closed (D-01). The rest, ordered by what they block, with a default that takes effect if unanswered.

| # | Question | Blocks | Default if unanswered |
|---|---|---|---|
| Q10 | Who does the prototype get piloted with, given that every participant must run it? | Pilot recruitment only — **blocks no slice** | Internal use and consenting participants first. Answering it is what triggers ADR-12, not the reverse |

**Deferred to ADR-12, blocking nothing in the prototype:** which conferencing platform to integrate with first (Q11), build vs. buy for a future ingress (Q12), and whether the thesis is meeting memory or a multilingual meeting layer (Q13). These are recorded as open product hypotheses, not pending decisions.
| Q2 | GPU availability, inference location, EU data residency for audio/transcripts/LLM | **Slice 4 and Slice 5** | Slices 0–3 proceed on fakes regardless |
| Q3 | Raw audio retention and consent | Slice 5 (scrubbing), Slice 7 (retention job) | Store, 30-day retention, consent by joining |
| Q5 | Participant ceiling | Slice 6 queue/GPU sizing | 4 hard limit |
| Q4 | Auth model for the pilot | Slice 7 | Magic-link host + link-based guests |
| Q8 | Deployment target | Slice 7 | Single VM, Docker Compose, GPU |
| Q6 | UI language | Cosmetic, any slice | French only |
| Q9 | Manual transcript corrections | Out of scope | Deferred |
| Q7 | Stack confirmation | All | Python/FastAPI + React/TS + PostgreSQL as specified |

The important structural property: **Q2 does not block the start of work.** Slices 0–3 run entirely on `FakeRecognizer` and `FakeLLMProvider`, which is the whole point of the adapter seam.

---

## 9. Definition of done for the prototype

The prototype is complete when Slices 0–6 are VERIFIED in `PROJECT_STATE.md` and the eight success criteria in tech spec §1.3 each map to a named passing test. Slice 7 is the gate for putting a real customer's conversation through it.

The question the prototype answers, and the only one it needs to:

> **Does realtime audio → ASR → attribution → transcript → intelligence work end to end, reliably, in French?**

Not claimed at that point, and recorded as such: horizontal scale, mixed-audio diarization, transcript editing, billing, multi-language, external conferencing-platform integration, ownership of the media plane, and any legal sign-off on recording consent.
