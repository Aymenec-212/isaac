# Mosaïque — Architecture Direction (hypotheses until Phase 0 validates them)

## Conceptual topology
```text
Browser (authenticated SaaS frontend, LiveKit SDK)
    ├── App API (FastAPI): identity authorization, organizations, meetings,
    │                       meeting history, transcript and action review
    └── LiveKit Cloud (hosted WebRTC/SFU audio meeting)
               │ participant-specific subscribed microphone tracks
               ▼
      Mosaïque Pipecat worker (separately deployable)
         LiveKitTransport → identity-aware routing
           ├── isolated audio/STT session A ─┐
           ├── isolated audio/STT session B ─┼── shared vLLM Voxtral Realtime on Modal L4
           └── isolated audio/STT session C ─┘       (concurrency/batching measured)
               │ normalized transcript events (participant, source time, revision)
               ▼
      Transcript lifecycle and persistence (PostgreSQL)
               │ completed meeting
               ▼
      Async meeting intelligence (summary/decision/action + evidence)
               │ reviewed + authorized
               ▼
      Connector (Linear OR Jira) → external ticket + audit/status linkage
```

## Invariants and boundaries
- LiveKit Cloud only operates meeting media; the application API owns meeting permissions and issues appropriately-scoped, short-lived LiveKit tokens.
- The Pipecat worker uses its LiveKit transport; `audio_in_user_tracks`/participant-tagged frames are a starting hypothesis to confirm against **pinned** versions/source.
- Every participant has a distinct stateful STT session and queue. Audio from different users must not be concatenated to achieve batching.
- Many remote STT connections may share one model instance/GPU; **vLLM's real batching and scheduling require experimental proof** at 1/2/4 streams.
- Pipecat handles available framing, transport and processing primitives; write a router/adapter only where upstream APIs lack domain-specific functionality.
- Canonical time and segment IDs cannot be inferred from transcript response arrival order. Interim and final output, edits and reconnects need explicit semantics.
- One real user can have multiple connections; association among authenticated user, LiveKit identity, track and ASR session must be explicit.
- All durable business state persists in PostgreSQL; don't rely on in-memory state for meeting history or approval decisions.
- Separate realtime path from async LLM extraction and external integration writes. Use recoverable/idempotent jobs as needed, but avoid speculative queues and microservices.
- Domain modules must not import LiveKit/Pipecat/vLLM/Modal SDKs. Meaningful adapters at infrastructure boundary only.

## Candidate domain modules (not compulsory classes)
- Identity/workspaces: authenticated membership, roles, invitations and organization authorization.
- Meetings: lifecycle, participants, access, session history and transcript records.
- Transcription runtime: Pipecat transport, participant router, isolated STT sessions, remote protocol and cleanup.
- Meeting intelligence: summarization, decisions, action extraction, evidence validation and human review.
- Integrations: connection permission, approved command execution, deduplication, external references and audit.

## Important unsolved engineering questions
1. Verify actual Pipecat frame shapes, participant IDs, pipeline composition and lifecycle APIs. Are per-user Pipelines necessary, or would equivalent isolated processors suffice?
2. Confirm Voxtral Realtime exact model and vLLM real-time API semantics (audio format, partial/final messages, commits and reconnects).
3. Confirm whether vLLM efficiently schedules/batches concurrent sessions on one L4 GPU. Measure memory/latency and Modal container scaling/cold starts.
4. Decide secure source-time/canonical ordering and handling overlaps, partials, gaps, retries and restarts.
5. Choose proven authentication integration, account deletion and invite flows without building identity cryptography.
6. Pick one ticket destination, tenant-scoped OAuth/scopes, approval semantics, idempotency/reconciliation after ambiguous provider outcomes.
7. Decide transcription disclosures and retention defaults suitable for actual pilot customers and applicable law.
8. Define boundaries, failures and observability without adding gratuitous services.

## Existing repository
Phase 0 must inventory existing FastAPI, React, PostgreSQL, WebSocket protocol, ASR runtime, summaries and tests, and document what gets reused, replaced or removed. This document must be revised to reflect **verified code**, with ADRs for consequential choices.
