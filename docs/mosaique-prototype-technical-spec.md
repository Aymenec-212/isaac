# Mosaïque — Technical Specification

> **Current amendment — 2026-09-12:** [Two-user voice / Azure ASR architecture](two-user-cloud-architecture.md)
> records the maintainer's new priority and supersedes companion-only D-01/ADR-01,
> the WebRTC exclusion and older single-user-first sequencing where they conflict.
> Direct WebRTC/TURN carries voice; the existing PCM WebSocket and ASR seams remain.
> Work proceeds one slice, one documented PR, review/merge, then the next slice.
> R0 is documentation only; deployment review is pending and no new feature or
> infrastructure is claimed implemented. Historical text below retains its original
> evidence; use the root PROJECT_STATE.md and the R0 sequence for current next work.

## Smallest Viable Remote-Meeting Prototype (PRD Stage 2 → Stage 4)

**Version:** 0.1 (draft for review)
**Date:** 2026-09-03
**Status:** Awaiting decisions on the open questions in §17 before implementation starts.
**Target maturity:** Level 1 (functional prototype) with the seams required for Level 2 already in place.

---

## 0. How to read this document

- §1–§3 define what "smallest viable" means and the architecture at process level.
- §4–§10 are the contracts a new engineer would implement against: domain model, state machine, HTTP/WebSocket protocol, audio format, ASR adapter, transcript semantics.
- §11–§15 cover finalization, meeting intelligence, security/privacy, reliability, and observability.
- §16 lists architectural decisions (decided vs. proposed).
- §17 lists open questions that need an answer from the product owner.
- §18 is the implementation sequence.

Nothing here is code. Where a value is a guess that must be measured (latency budgets, segmentation thresholds), it is marked **[measure]**.

---

## 1. Prototype definition

### 1.1 What it must do

A host creates a meeting in a browser, shares a link, and 2–4 remote participants join from their own browsers. Each participant's microphone is streamed separately to the backend. French speech is transcribed live with participant attribution and rendered in every participant's browser. When the host ends the meeting, the transcript is durably stored, and a summary, decisions, and action items are generated asynchronously and shown on a review page.

This maps to PRD §20 (MVP success criteria) and PRD Stages 2 and 4. Stage 3 (four people) is a load parameter, not a new feature.

### 1.2 Explicit non-goals for this prototype

- Mixed-audio diarization or source separation (PRD Stage 5).
- Carrying voice between participants (see Q1 in §17 — this is the single most important unresolved product question).
- LiveKit / WebRTC media routing.
- Multi-language switching; the UI and ASR are French-first.
- Billing, CRM/calendar integrations, admin consoles.
- Horizontal scaling across multiple backend hosts.

### 1.3 Success criteria (testable)

| # | Criterion | How it is verified |
|---|-----------|--------------------|
| 1 | Two browsers on different networks join the same meeting | e2e test with two headless clients |
| 2 | Both audio streams reach the backend with < 2% dropped frames over 30 min | audio metrics `frames_received`, `frames_dropped` |
| 3 | Live transcript p95 perceived latency ≤ 2.0 s **[measure]** | `transcript.first_word_latency_ms` metric from replay harness |
| 4 | Every final segment carries a participant_id | DB constraint + unit test |
| 5 | A 10 s disconnect resumes without duplicate segments or duplicate participants | realtime replay test with injected disconnect |
| 6 | `POST /end` twice produces one COMPLETED meeting and one intelligence job | idempotency test |
| 7 | Summary/decisions/actions appear on the review page within 90 s of ending **[measure]** | e2e test with fake LLM |
| 8 | Backend restart mid-meeting does not lose already-final segments | integration test (kill worker, restart, read DB) |

---

## 2. System architecture

### 2.1 Runtime topology (prototype)

Four processes, one Docker Compose file. Logical boundaries are kept even where processes are merged.

```text
 Browser A ──┐                                   ┌──────────────┐
 Browser B ──┼── HTTPS + WSS ──►  app-server  ◄──►│  asr-runtime │ (Kyutai STT-1B, GPU)
 Browser C ──┘                    (Python)        └──────────────┘
                                     │  ▲
                                     │  │
                              ┌──────▼──┴──────┐
                              │   PostgreSQL   │  meetings, participants, segments, jobs
                              └────────────────┘
                                     │
                              ┌──────▼─────────┐
                              │ audio store    │  local volume now; S3-compatible later
                              └────────────────┘
                                     │
                              ┌──────▼─────────┐
                              │ LLM provider   │  behind an interface (see §12)
                              └────────────────┘
```

**app-server** hosts, in one process for now, four separable runtimes (engineering skill §28):

```text
app-server
 ├── api          REST: meetings, join, end, transcript, outputs
 ├── gateway      WebSocket auth, connection lifecycle, heartbeats
 ├── runtime      per-meeting state, per-participant audio queue → ASR session, transcript reconciliation
 └── processor    polls jobs table, runs meeting intelligence (may be started as a separate process via a flag)
```

**asr-runtime** is a separate process from day one. Reason: GPU isolation, independent restart, and it is the component most likely to be swapped (Darija model, different runtime). The app-server only talks to it through the `StreamingRecognizer` adapter (§8).

### 2.2 Data flow (live)

```text
mic → AudioWorklet (48 kHz float → 24 kHz s16le mono, 80 ms frames)
    → WebSocket binary frame [header + PCM]
    → gateway (auth, validation)
    → runtime: bounded per-stream queue
    → ASR adapter session (one per participant stream)
    → word events with timestamps
    → segmenter (open segment = interim; closed segment = final)
    → (a) broadcast to all participants' sockets
      (b) final segments written to PostgreSQL
    → raw PCM appended to per-participant audio file (for replay + FR-11 navigation)
```

### 2.3 Data flow (end of meeting)

```text
POST /meetings/{id}/end (idempotent)
    → state LIVE → FINALIZING
    → stop accepting audio; drain queues with deadline
    → flush ASR sessions; commit remaining segments
    → transcript_version = 1; state → COMPLETED
    → insert job(meeting_id, transcript_version, processor_version)
    → processor: build prompt from final segments → LLM → validate JSON → store outputs
    → UI polls GET /outputs (or receives meeting.outputs.ready over WS if still connected)
```

---

## 3. Repository structure

Python backend, TypeScript frontend (see ADR-02). Adapted from engineering skill §21.

```text
mosaique/
  backend/
    src/mosaique/
      config/           typed settings (pydantic-settings); fail fast on missing keys
      app/
        api/            FastAPI routers: meetings, participants, transcript, outputs
        auth/           token issue/verify, authorization helpers
      domain/           Meeting, Participant, TranscriptSegment, MeetingOutputs, state machine (pure)
      realtime/
        gateway/        WS endpoint, hello/auth, heartbeat, backpressure signalling
        protocol/       message schemas (pydantic), binary frame codec
        sessions/       ParticipantSession: queue, reconnect grace, sequence tracking
      speech/
        interfaces/     StreamingRecognizer, ASRSession, AudioChunk, WordEvent
        adapters/
          kyutai/       the only module that knows about Kyutai / moshi
          fake/         deterministic recognizer for tests
        audio/          format validation, resampling (only if ever needed server-side)
      transcript/       Segmenter (words → interim/final), reconciliation rules
      intelligence/     LLMProvider interface, prompt builder, output schema, fake provider
      persistence/
        models/         SQLAlchemy models
        repositories/   MeetingRepo, SegmentRepo, JobRepo
        migrations/     alembic
      jobs/             processor loop (SELECT ... FOR UPDATE SKIP LOCKED)
      observability/    metrics registry, structured logging, correlation context
    tests/
      unit/ integration/ realtime/ e2e/
      fixtures/audio/   short French PCM fixtures for the replay harness
    tools/replay/       audio replay harness (§14.3)
  frontend/
    src/
      audio/            worklet processor, capture pipeline, level meter
      realtime/         WS client, reconnect, transcript reconciler
      meeting/          live view, participants panel, status bar
      review/           summary / decisions / actions / transcript with audio scrubbing
      api/              typed client generated from OpenAPI
  docs/adr/
  docker-compose.yml
```

---

## 4. Domain model

All tenant-owned rows carry `organization_id` from the first migration even though the prototype seeds one organization. Cross-tenant reads fail closed at the repository layer.

```text
Organization(id, name, created_at)
User(id, organization_id, email, display_name, created_at)

Meeting(
  id ULID, organization_id, host_user_id, title,
  state ENUM(CREATED, JOINABLE, LIVE, FINALIZING, COMPLETED, FAILED, CANCELLED),
  language 'fr', transcript_version INT NULL,
  asr_version TEXT, transcript_schema_version INT,
  started_at, ended_at, created_at, updated_at
)

Participant(
  id ULID, meeting_id, organization_id,
  user_id NULL, display_name, role ENUM(host, guest),
  join_token_hash, created_at
)
-- One Participant per human. Reconnects reuse it; never create a second row.

AudioSession(
  id ULID, meeting_id, participant_id,
  started_at, ended_at, sample_rate INT, frames_received INT, frames_dropped INT,
  audio_object_key TEXT NULL     -- path to stored PCM/WAV for this session
)
-- A participant may have several AudioSessions (one per reconnect beyond the grace period).

TranscriptSegment(
  id ULID, meeting_id, organization_id, participant_id, audio_session_id,
  sequence INT,                  -- monotonic per participant
  start_ms INT, end_ms INT,      -- relative to meeting.started_at
  text TEXT, words JSONB,        -- [{w, start_ms, end_ms}] for FR-11 navigation
  status ENUM(final, gap),       -- 'gap' marks audio that could not be transcribed
  created_at,
  UNIQUE(participant_id, sequence)
)
-- Interim text is never stored here.

MeetingOutputs(
  id, meeting_id, transcript_version, processor_version, llm_model TEXT,
  status ENUM(pending, running, succeeded, failed),
  summary TEXT, key_points JSONB, decisions JSONB, action_items JSONB, open_questions JSONB,
  error_code TEXT NULL, generated_at,
  UNIQUE(meeting_id, transcript_version, processor_version)
)

Job(
  id, kind 'meeting_intelligence', idempotency_key TEXT UNIQUE,
  payload JSONB, status, attempts INT, next_run_at, last_error TEXT, created_at
)
```

Ordering rule: within a participant, order by `sequence`; across participants, order by `start_ms` for display. Never by wall-clock `created_at`.

---

## 5. Meeting state machine

```text
CREATED ──(host opens room)──► JOINABLE ──(first audio frame OR host starts)──► LIVE
                                                                                │
                                              ┌─────────────────────────────────┘
                                              ▼
                                         FINALIZING ──(drain complete or deadline)──► COMPLETED
                                              │
                                              └──(unrecoverable persistence failure)──► FAILED
CREATED / JOINABLE ──(host cancels)──► CANCELLED
```

Rules (enforced in `domain/state.py`, pure functions, unit-tested):

- `end()` from LIVE → FINALIZING; from FINALIZING or COMPLETED → no-op returning current state (idempotent).
- Audio frames are rejected with `MEETING_NOT_LIVE` unless state ∈ {JOINABLE, LIVE}; the first accepted frame moves JOINABLE → LIVE.
- COMPLETED is terminal for realtime; a `FINALIZING` meeting whose process crashes is picked up on startup by a recovery routine that re-runs the drain (ASR sessions are gone, so remaining audio in the stored file is marked as a `gap` segment; offline re-transcription of gaps is a Level 2 feature).
- Transition attempts are logged as `meeting_state_transition{from,to,ok}`.

---

## 6. HTTP API

All routes require a bearer token except `POST /meetings/{id}/join` which accepts the invite token. All responses use the error envelope `{error: {code, message, request_id}}` with codes from the taxonomy in §13.4.

```text
POST   /meetings                         host creates; returns {meeting, host_token, invite_url}
POST   /meetings/{id}/join               body {display_name, invite_token}; returns {participant, session_token, ws_url}
GET    /meetings/{id}                     state, participants, timings
POST   /meetings/{id}/end                 host only; idempotent; returns state
GET    /meetings/{id}/transcript          final segments ordered for display; ?q= for text search (ILIKE for now)
GET    /meetings/{id}/outputs             {status, summary, decisions, action_items, ...}; 202 while pending
GET    /meetings/{id}/audio/{session_id}  streams stored audio (Range supported) for review-page scrubbing
GET    /meetings                          list for the caller's organization
```

Authorization: every handler resolves `(organization_id, user_or_participant)` from the token and checks meeting membership server-side. Meeting IDs are ULIDs but are never treated as secrets.

---

## 7. Realtime protocol (WebSocket)

One socket per participant per meeting. Text frames carry JSON control/transcript messages; binary frames carry audio. The protocol is versioned (`v: 1`) so the transport can be swapped for LiveKit data channels later without changing the runtime.

### 7.1 Client → server

```text
text   {"v":1,"type":"hello","session_token":"…","last_ack_sequence":123,"client":{"ua":"…","sample_rate":24000}}
binary [u8 version=1][u32 seq][u32 capture_ms][s16le PCM × 1920 samples]   // 80 ms @ 24 kHz = 3840 bytes payload
text   {"v":1,"type":"audio.pause"}          // user muted; server keeps session, does not expect frames
text   {"v":1,"type":"audio.resume"}
text   {"v":1,"type":"ping","t":…}
```

`capture_ms` is milliseconds since the client's capture start; the server maps it to meeting time on `hello` and re-anchors on resume. `seq` is per audio session and must increase by exactly 1; gaps are counted, duplicates are dropped.

### 7.2 Server → client

```text
{"type":"hello.ok","participant_id":"…","meeting_state":"LIVE","meeting_started_at":…,"resume":true|false}
{"type":"transcript.delta",         "participant_id":"…","sequence":18,"revision":3,"status":"interim","text":"Bonjour, je pense qu'on"}
{"type":"transcript.segment.final", "participant_id":"…","sequence":18,"revision":4,"status":"final","text":"…","start_ms":12500,"end_ms":16300,"segment_id":"…"}
{"type":"participant.joined"|"participant.left"|"participant.reconnecting","participant_id":"…","display_name":"…"}
{"type":"participant.speaking","participant_id":"…","active":true|false}
{"type":"stream.status","participant_id":"…","status":"listening"|"receiving"|"transcribing"|"delayed"|"unavailable","lag_ms":…}
{"type":"meeting.state","state":"FINALIZING"|"COMPLETED"}
{"type":"meeting.outputs.ready"}
{"type":"error","code":"AUDIO_INVALID_FRAME","message":"…","fatal":false}
{"type":"pong","t":…}
```

### 7.3 Reconciliation contract for clients

- Key = `(participant_id, sequence)`.
- A message is applied only if `revision` > the stored revision for that key.
- `transcript.segment.final` freezes the key; later deltas for it are ignored.
- On `hello.ok` with `resume:true`, the client requests `GET /transcript` to backfill anything missed, then continues applying live messages. Duplicates are harmless under the rule above.

### 7.4 Connection lifecycle

- Server pings every 10 s; a socket with no pong or frame for 30 s is considered dead.
- **Reconnect grace:** on socket loss, the ParticipantSession and its ASR session are kept alive for 30 s **[measure]**. A `hello` with the same session token within that window resumes in place; audio frames the client buffered while offline (client keeps up to 15 s) are accepted if their `seq` continues the sequence.
- Beyond the grace period the ASR session is ended (open segment finalized), a new AudioSession is created on reconnect, and the participant row is reused.
- A second socket with the same session token closes the first (`error SESSION_REPLACED`), preventing double audio from two tabs.

---

## 8. Audio pipeline

### 8.1 Canonical format

```text
PCM signed 16-bit little-endian, mono, 24 000 Hz, 80 ms frames (1920 samples, 3840 bytes)
```

This is chosen because it is the native input of Kyutai's Mimi codec (24 kHz, 80 ms frame hop). **Verify against the current Kyutai model card before implementation** (dependency discipline, skill §38). If a future ASR needs 16 kHz, the conversion happens in `speech/audio/`, at the adapter boundary, nowhere else.

### 8.2 Client capture

- `getUserMedia({audio: {channelCount:1, echoCancellation:true, noiseSuppression:true, autoGainControl:true}})`. Echo cancellation is essential if participants hear each other through another channel on the same device (see Q1).
- An `AudioWorkletProcessor` resamples from the device rate (usually 48 kHz) to 24 kHz, converts to Int16, and posts 80 ms frames. Doing this client-side keeps the wire format identical to the model format and the bandwidth at 48 KB/s per participant.
- The worklet also emits an RMS level every 100 ms for the "speaking" indicator and for detecting a silent microphone (level ≈ 0 for 10 s → UI warning "no audio detected").

### 8.3 Server validation (gateway, before the queue)

Reject the frame (and count `audio_frames_rejected{reason}`) if: header version ≠ 1; payload length ≠ 3840; `seq` ≤ last seen (duplicate); frame arrives while meeting is not JOINABLE/LIVE. A gap in `seq` is accepted, counted as `audio_frames_missing`, and the segmenter inserts a `gap` marker if the gap exceeds 2 s.

### 8.4 Bounded queue and overload policy

Per participant stream: a queue of 62 frames (≈ 5 s).

```text
depth < 25 (2 s)     normal                      stream.status = transcribing
depth 25–62          lagging                      stream.status = delayed, lag_ms reported
queue full           overload                     frame is NOT dropped from the audio file;
                                                  it is dropped from the ASR queue, counted as
                                                  asr_frames_skipped, and a 'gap' segment is
                                                  emitted covering the skipped span
sustained full > 15 s  stream failure            ASR session closed, stream.status = unavailable,
                                                  audio still recorded; client shows a red state
```

Final transcript text is never silently lost: every skipped span is either a visible `gap` segment or recoverable from the stored audio.

### 8.5 Audio storage

Raw PCM per AudioSession is appended to a local file (`audio/{meeting_id}/{session_id}.pcm`) and converted to WAV/FLAC at finalization. This serves three product needs: FR-11 timestamp navigation, the replay harness, and offline re-transcription of gaps. Retention policy is open (Q3).

---

## 9. ASR adapter

### 9.1 Product-neutral interface (`speech/interfaces`)

```python
class StreamingRecognizer(Protocol):
    async def open_session(self, cfg: ASRSessionConfig) -> ASRSession: ...

class ASRSession(Protocol):
    async def push_audio(self, chunk: AudioChunk) -> None: ...          # 80 ms canonical frame
    def events(self) -> AsyncIterator[WordEvent | EndOfTurnEvent | ASRErrorEvent]: ...
    async def flush(self) -> None: ...                                  # push silence/end marker, drain
    async def close(self) -> None: ...
    def health(self) -> ASRHealth: ...                                  # lag, last_event_at

WordEvent(text: str, start_ms: int, end_ms: int | None, confidence: float | None)
EndOfTurnEvent(at_ms: int, probability: float)
```

Nothing outside `speech/adapters/kyutai/` imports Kyutai/moshi/torch types.

### 9.2 Kyutai adapter (`kyutai/stt-1b-en_fr`)

What is relied upon (to be re-verified against the current Kyutai docs before coding):

- Streaming, 24 kHz input, emits word-level text with timestamps after a fixed delay of roughly 0.5 s; text is not retracted once emitted.
- Provides a semantic VAD / end-of-turn signal.
- Available runtimes include a Rust `moshi-server` exposing a WebSocket streaming API and a PyTorch implementation.

Adapter decision: **run `moshi-server` as the `asr-runtime` container and connect to it over WebSocket**, one ASR socket per participant stream. The adapter translates its wire format into `WordEvent`/`EndOfTurnEvent`. If `moshi-server` turns out not to support concurrent independent streams cleanly, fall back to an in-process PyTorch adapter inside a dedicated `asr-runtime` service that exposes the same protocol. Either way, the app-server is unchanged.

Adapter responsibilities: reconnect to the ASR runtime with bounded backoff (3 attempts, 0.5 s → 4 s with jitter); report `ASR_TIMEOUT` if no event arrives for 5 s while audio is being pushed **[measure]**; expose `health()` for the stream status.

### 9.3 Segmenter (`transcript/segmenter.py`)

Because the model streams final words continuously, "interim vs. final" is a product-layer concept:

```text
words arrive → appended to the open segment → broadcast as transcript.delta (revision++)
segment closes (→ transcript.segment.final, persisted) when any of:
   • EndOfTurnEvent with probability ≥ 0.5 **[measure]**
   • silence (no words) ≥ 700 ms after ≥ 1 word **[measure]**
   • open segment duration ≥ 15 s (hard cap, split at last word boundary)
   • flush() at end of meeting or session close
```

Pure, deterministic, and unit-tested with word sequences; the same code runs in the replay harness.

---

## 10. Transcript persistence and consistency

- Only final segments are written, in a single transaction per segment (`INSERT ... ON CONFLICT (participant_id, sequence) DO NOTHING`), so a retried write is a no-op.
- The runtime holds interim state in memory only; it is disposable. Process memory is never the authoritative record (skill §43).
- Per-participant `sequence` is allocated by the runtime, persisted with the segment, and restored from the DB on process restart (`MAX(sequence)+1`).
- `meeting.transcript_version` is NULL while LIVE and set to 1 at COMPLETED. Any later manual correction feature would bump it, which automatically invalidates derived outputs (unique key in `MeetingOutputs`).

---

## 11. Meeting finalization

```text
POST /end (host)
  1. state LIVE → FINALIZING (idempotent; concurrent calls get the same result)
  2. gateway rejects new audio frames (MEETING_NOT_LIVE, fatal:false, client shows "finalizing")
  3. for each ParticipantSession, in parallel, with a 20 s deadline **[measure]**:
       drain queue → push remaining frames → session.flush() → segmenter.close_open()
  4. persist remaining segments; close audio files; write AudioSession.ended_at
  5. if any session missed the deadline: emit 'gap' segment for undrained span, log finalize_drain_timeout
  6. transaction: meeting.state = COMPLETED, transcript_version = 1, ended_at
                  + INSERT Job(idempotency_key = f"{meeting_id}:1:{PROCESSOR_VERSION}")
  7. broadcast meeting.state COMPLETED; close sockets with code 1000
```

Recovery: on startup, any meeting in FINALIZING is re-driven from step 4 with no live sessions; this is safe because steps 4–6 are idempotent.

---

## 12. Meeting intelligence

### 12.1 Processing

- The processor loop claims one job at a time (`FOR UPDATE SKIP LOCKED`), marks `MeetingOutputs.status = running`, builds the prompt from **final segments only**, calls the `LLMProvider`, validates the response against a strict JSON schema, stores the result, and marks `succeeded`.
- Timeout 60 s per LLM call; up to 3 attempts with exponential backoff (30 s, 2 min, 8 min); then `failed` with `error_code`. A failed job never affects the transcript or meeting state.
- Long meetings: if the transcript exceeds the provider's context budget, chunk by time (e.g. 20-minute windows), extract per chunk, then run a merge pass. The prototype implements single-pass and asserts on length; chunking is scheduled in the sequence (§18).

### 12.2 Interface

```python
class LLMProvider(Protocol):
    async def complete_json(self, system: str, user: str, schema: dict, deadline_s: float) -> dict: ...
```

First implementation: a hosted API (provider decided in Q2). A `FakeLLMProvider` returns canned outputs for tests.

### 12.3 Output schema (stored as JSONB, validated before storage)

```json
{
  "summary": "string (≤ 150 words, French)",
  "key_points": ["string"],
  "decisions": [{"text": "string", "evidence_segment_ids": ["…"]}],
  "action_items": [{"text": "string", "owner_participant_id": "… | null", "owner_text": "string | null",
                    "due_text": "string | null", "evidence_segment_ids": ["…"]}],
  "open_questions": [{"text": "string", "evidence_segment_ids": ["…"]}]
}
```

`evidence_segment_ids` is required: every decision/action must point at ≥ 1 segment. The prompt provides segments as `[seg_id] Speaker (mm:ss): text`, and the validator rejects IDs that do not exist. This gives the traceability PRD §16 asks for and makes hallucinated actions detectable.

### 12.4 Prompt-injection posture

Transcript text is untrusted. The system prompt states that the transcript is data, not instructions; the transcript is delimited; outputs are schema-validated; and no tool use or external actions are available to the summarizer. This is a Level 1 mitigation, not a complete defense; noted in the security checklist.

---

## 13. Security, auth, privacy

### 13.1 Authentication (prototype)

- Host: a User account. Simplest viable: email + magic-link, or a pre-provisioned account for the pilot organization (Q4).
- Guest: `POST /join` with the invite token (random 128-bit, stored hashed, expires with the meeting) returns a `session_token` (signed, 12 h, bound to `participant_id`). The WebSocket `hello` presents this token; audio is refused until `hello.ok`.
- Tokens never appear in URLs after the initial invite link; the invite token is exchanged once per participant identity.

### 13.2 Authorization

Every meeting resource check is `meeting.organization_id == principal.organization_id AND (principal is host OR principal.participant.meeting_id == meeting.id)`. Implemented once in `app/auth/authorize.py`, unit-tested with a cross-tenant case.

### 13.3 Privacy and data lifecycle (defaults, pending Q3)

- Recording consent: the join page states that audio is recorded and transcribed; joining is consent. Displayed before microphone permission is requested.
- Raw audio: stored (needed for FR-11 and replay). Default retention 30 days, then deleted; transcript retained until the meeting is deleted.
- Deletion: `DELETE /meetings/{id}` (host) removes segments, outputs, audio files, and jobs in one workflow; a deletion audit row is kept.
- Logs never contain transcript text, audio, tokens, or e-mail addresses. Debug capture of transcript text is possible only behind `LOG_TRANSCRIPT_TEXT=true`, refused in production config.

### 13.4 Error taxonomy (public codes)

```text
AUTH_INVALID_TOKEN, AUTH_FORBIDDEN, MEETING_NOT_FOUND, MEETING_NOT_LIVE, MEETING_INVALID_TRANSITION,
AUDIO_INVALID_FRAME, AUDIO_QUEUE_OVERLOADED, SESSION_REPLACED, TRANSPORT_STALLED,
ASR_UNAVAILABLE, ASR_TIMEOUT, PERSISTENCE_UNAVAILABLE, POSTPROCESSING_FAILED, RATE_LIMITED, INTERNAL_ERROR
```

### 13.5 Pre-pilot security checklist

- [ ] CORS restricted to the frontend origin; WSS origin check
- [ ] Rate limits: `POST /meetings` per user, `POST /join` per IP, max 4 participants per meeting, max 3 concurrent meetings per organization
- [ ] Frame size hard limit at the gateway (any binary frame ≠ 3849 bytes rejected)
- [ ] Dependency audit (`pip-audit`, `npm audit`) and container scan in CI
- [ ] Secrets only from environment / secret manager; startup fails if any are missing
- [ ] Tenant-isolation test suite green

---

## 14. Reliability and testing

### 14.1 Failure matrix

| Failure | Detection | Behavior | User sees |
|---|---|---|---|
| Mic permission denied | `getUserMedia` rejects | No socket opened | Blocking explanation with retry |
| Silent microphone | RMS ≈ 0 for 10 s | Warning event | "No audio detected" banner |
| Tab suspended / socket drops | missing pong 30 s | 30 s grace, then session closed, segment finalized | "Reconnecting…" then "Reconnected" or "Disconnected" |
| Duplicate / out-of-order frames | `seq` check | Drop duplicates, count gaps | Nothing unless gap > 2 s → gap marker |
| ASR runtime slow | queue depth | `delayed` status, then gap emission | Yellow "Transcription delayed (3 s)" |
| ASR runtime down | adapter reconnect fails | Stream `unavailable`; audio still recorded | Red "Transcription unavailable — audio is still being recorded" |
| Two tabs, same participant | second `hello` | First socket closed | "Meeting opened elsewhere" |
| Host ends twice / double click | state machine | Second call is a no-op | Single "Finalizing…" |
| App-server crash mid-meeting | supervisor restart | Final segments persist; live state lost; clients reconnect, get new AudioSession | Brief "Reconnecting…"; interim text lost |
| App-server crash during FINALIZING | startup recovery | Drain re-run without live sessions | Meeting completes with possible gap markers |
| DB unavailable while LIVE | write errors | Segments buffered in memory up to 200, then stream `unavailable`; audio file continues | Status bar warning |
| LLM provider down | job failures | Retries with backoff; transcript unaffected | "Summary is taking longer than usual" then "Summary failed — retry" |
| Deployment during a meeting | SIGTERM | Graceful shutdown: stop accepting joins, finalize open segments, close sockets with code 1012; documented limitation for Level 1 | "Connection reset, reconnecting" |

### 14.2 Test plan

- **Unit:** state machine transitions; segmenter (word timing cases, end-of-turn, cap); client-side reconciler (revisions, out-of-order); frame codec and validation; authorization matrix; output schema validation including bad `evidence_segment_ids`.
- **Integration (fake ASR, fake LLM, real PostgreSQL):** join → audio → segments persisted; end → COMPLETED → job → outputs; idempotent end; startup recovery from FINALIZING; deletion workflow.
- **Realtime (replay harness):** 2 and 4 participants; injected 10 s disconnect with buffered frames; duplicate frames; 5 s ASR stall; ASR socket drop; 60-minute accelerated run for memory stability.
- **E2E (Playwright, 2 browser contexts, fake ASR):** create → join ×2 → synthetic mic → live transcript visible in both → end → review page shows outputs.
- **Smoke (real Kyutai, nightly or on demand):** replay a 3-minute French fixture at real time; assert WER ≤ agreed threshold and p95 first-word latency.

### 14.3 Replay harness (`tools/replay`)

Takes N PCM fixtures + a timing script (start offsets, pauses, disconnect at t, duplicate frames at t), connects to the gateway as N participants, and streams with a speed factor (1× or ≥ 10×). Emits a JSON report: frames sent, transcript events received, first-word latency per segment, and the final transcript for assertion. This is the primary debugging tool; it must exist before reconnect handling is built.

---

## 15. Observability

Correlation IDs on every log line and metric label where cardinality allows: `request_id, meeting_id, participant_id, audio_session_id, asr_session_id`.

**Metrics (Prometheus naming):**

```text
meetings_active, participants_active, ws_connections_total{result}, ws_reconnects_total, ws_disconnects_total{cause}
audio_frames_received_total, audio_frames_rejected_total{reason}, audio_frames_missing_total, audio_queue_depth{participant}
asr_sessions_active, asr_events_total{type}, asr_errors_total{code}, asr_frames_skipped_total
transcript_first_word_latency_ms (histogram), transcript_segment_final_latency_ms (histogram), transcript_gap_segments_total
finalize_duration_ms (histogram), finalize_drain_timeouts_total
jobs_total{kind,status}, job_duration_ms{kind}, llm_call_duration_ms{provider}, llm_errors_total{code}
meetings_completed_total, meetings_failed_total
```

Latency decomposition recorded per segment: `capture_ms → gateway_recv → queue_dequeue → asr_first_event → broadcast_sent`.

**Health endpoints:** `/livez` (process up), `/readyz` (DB reachable AND ASR runtime reachable), `/health/deps` (per-dependency detail; LLM provider listed but does not affect readiness).

**Alerts for the pilot:** ASR runtime unreachable > 1 min; `readyz` failing; job failure rate > 20% over 15 min; p95 first-word latency > 4 s over 5 min.

---

## 16. Architectural decisions

### 16.1 Decided (aligned with PRD and engineering skill; ADRs to be written in `docs/adr/`)

| ADR | Decision | Why | Revisit trigger |
|---|---|---|---|
| 01 | WebSocket + raw PCM for transport; no LiveKit | Simplest debuggable path; per-participant streams already give attribution | Need to carry voice between participants, > 4 participants, or mobile network loss rates unacceptable |
| 02 | Python (FastAPI, asyncio) backend; React + TypeScript frontend | Kyutai ecosystem is Python-first; async fits the realtime path; TS gives typed protocol on both ends | CPU-bound gateway work exceeds asyncio capacity |
| 03 | Kyutai STT-1B en/fr behind `StreamingRecognizer`; run as separate `asr-runtime` process | Streaming-native, French, GPU isolation, swappable | WER on real meetings unacceptable, or Darija model adopted |
| 04 | PostgreSQL for all durable state including the job queue | One dependency; transactional; `SKIP LOCKED` is enough for one worker | Job throughput or multi-worker needs justify a broker |
| 05 | Store only final segments; interim state in memory | Skill §7/§43; keeps DB clean and reconciliation deterministic | Product wants "how the text evolved" replay (unlikely) |
| 06 | Store raw per-participant audio | Required for FR-11, replay harness, gap recovery | Privacy constraint from pilot customer (Q3) |
| 07 | Meeting intelligence asynchronous, derived, versioned, evidence-linked | Skill §17–18; auditable outputs | — |
| 08 | `organization_id` on every table from migration 1 | Cheap now, expensive later | — |
| 09 | Single app-server process with four separable runtimes | Skill §28; split when metrics justify | ASR adapter CPU or GC pauses degrade API latency |

### 16.2 Proposed, awaiting confirmation

| Topic | Proposal | Alternative |
|---|---|---|
| ASR runtime | `moshi-server` (Rust) over WebSocket | In-process PyTorch adapter in its own container |
| Client resampling | In AudioWorklet, send 24 kHz PCM | Send device-rate PCM, resample server-side (more bandwidth, simpler client) |
| Guest auth | Invite link + display name, no account | Every participant must have an account |
| Host auth | Magic link email | Pre-provisioned pilot accounts |
| Segmentation defaults | end-of-turn ≥ 0.5, silence 700 ms, cap 15 s | To be tuned with the replay harness against real French meetings |

---

## 17. Open questions (need your decision)

Ordered by how much they block implementation.

**Q1 — Is Mosaïque the call, or a companion to an existing call?** The PRD says two remote people join and both streams reach the backend, but never says participants hear each other through Mosaïque. If Mosaïque must carry voice, WebRTC/LiveKit becomes a prerequisite, not a later option, and ADR-01 is wrong. If it is a companion (each participant keeps Mosaïque open alongside Meet/Teams/phone), the design above holds, but two things follow: echo cancellation must be on so the other party's voice from the speakers is not attributed to the local mic, and the product pitch changes ("run this next to your call"). **My recommendation: companion mode for the prototype.**

**Q2 — Where does inference run, and what are the data-residency constraints?** (a) Do you have a GPU for Kyutai (local workstation, cloud instance, region)? CPU-only viability of STT-1B at real time needs to be checked before committing. (b) Which LLM provider for summaries, and must audio/transcripts of French SMB clients stay in the EU? This decides whether the `LLMProvider` first implementation is a hosted API or a self-hosted model.

**Q3 — Raw audio retention and consent.** Storing audio is the default above because FR-11 needs it. Confirm: store it, 30-day retention, consent by joining. If a pilot customer refuses audio storage, FR-11 and gap recovery are dropped for them via a per-organization flag.

**Q4 — Auth model for the pilot.** Magic-link host accounts + link-based guests (proposed), or full accounts for everyone?

**Q5 — Participant ceiling for the prototype.** 2 for Stage 2, 4 for Stage 3 — is 4 the hard limit to design queues, GPU memory, and rate limits around?

**Q6 — UI language.** French-only UI, or French + English toggle from the start?

**Q7 — Stack confirmation.** Python/FastAPI + React/TS + PostgreSQL. Any existing code, hosting, or team-skill constraint that changes this?

**Q8 — Pilot deployment target.** Single VM with Docker Compose and a GPU, or a managed platform? This determines how much of §15 alerting is built now.

**Q9 — Manual transcript corrections in scope?** PRD §19 measures "user correction rate" but the MVP scope list does not include editing. If yes, `transcript_version` increments and outputs regenerate; it adds a review-page editor.

---

## 18. Implementation sequence

Each step ends with its tests green and the replay harness (from step 4 onward) passing.

```text
 1. Repo skeleton, typed config, PostgreSQL + migrations, domain model, state machine (unit tests)
 2. REST: create / join / get / end (idempotent) with auth + tenant checks (integration tests)
 3. Frontend: create meeting, join page with consent + mic permission, AudioWorklet capture, level meter
 4. WebSocket gateway + protocol + frame validation; FakeRecognizer; replay harness v1 (single stream)
 5. Segmenter + live transcript UI with interim/final rendering and client reconciler
 6. Durable final-segment persistence; raw audio recording; restart-safety test
 7. Kyutai adapter against asr-runtime; latency instrumentation; first real-model smoke test
 8. Reconnect grace, sequence resume, two-tab handling, stream status UI (realtime tests)
 9. Finalization workflow + startup recovery
10. Intelligence: LLMProvider, prompt, schema validation, jobs loop, review page, audio scrubbing
11. Observability: metrics, structured logs, health endpoints, minimal alerts
12. Four-participant replay under load; tune queue and segmentation thresholds; document budgets
13. Docker Compose deployment, graceful shutdown, security checklist, ADRs, runbook
```

Steps 1–6 are usable with the fake recognizer, so the product path is demonstrable before the GPU question (Q2) is settled.
