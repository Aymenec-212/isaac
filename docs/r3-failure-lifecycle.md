# R3 — recording and lifecycle during ASR failure

**Baseline:** merged R2, PR #21 (`61c9c49`). **Scope:** application lifecycle;
no GPU provisioning, region change, WebRTC, identity migration or ASR retuning.
Real NVIDIA interruption acceptance remains open.

## Problem and resulting behavior

Previously a recognizer opening failure could end the meeting's shared ingress
consumer. Fatal recognition errors were logged without changing the stream's
state. A stopped pump cancelled its event reader before terminal flush, leaving
tail words unread. A second end request could find the runtime already removed
and complete the meeting while the first request was still draining it.

R3 establishes the recording session before starting recognition in a separate
participant task. The shared consumer can accept and record both participants
while either recognizer opens. Open and push operations each have a five-second
budget; errors, unexpected reader termination, unhealthy sessions and the neutral
ASR timeout event make that participant's transcription unavailable. No model
library or transport type crosses the existing recognizer seam.

Recording continues during recognition failure. After five seconds, the next
received frame retries in a new AudioSession and inference session under the
same participant. The failed stream is closed, its available partial transcript
is finalized, and the unavailable range is persisted as a gap. The new session
starts at local sequence zero while socket resume retains the browser's sequence.
Its epoch is anchored to the first frame handled by the server, independently of
ASR startup. Existing buffered final sequences are included when selecting the
next segment number. There is no automatic retranscription of an outage.

An outage gap is conservative: it begins at reported transcription progress and
ends at the recorded input boundary. It can include partially recognized audio;
it is a warning that transcription is incomplete, not word-level proof of loss.
The live warning is immediate; the final gap is written on recovery or close.
A meeting in which every recognizer open failed has null ASR provenance, not a
fake-model label.

Audio files are flushed after writes. This detects ordinary write/flush failures
but is **not an fsync guarantee against power loss**. Storage errors report
`AUDIO_RECORDING_FAILED` and unavailable status without stopping the peer. The
browser no longer asserts that an ASR status proves successful recording.

## Transport and client changes

- A full or sealed ingress queue rejects admission explicitly. The gateway sends
  `INGRESS_UNAVAILABLE` and closes with 1013, allowing reconnect; it no longer
  silently continues after losing submitted audio. Rejected leave events are
  logged and existing idle cleanup still applies.
- Transcript fan-out sends to peers concurrently, with a one-second send budget
  and one-second close budget. A failed peer is removed only if that socket is
  still registered. Healthy peers receive the message without waiting for it.
- The local browser's transcription warning follows its own participant ID;
  another participant's healthy stream cannot clear it.
- `transcript.segment.final.status` now permits `gap` as well as `final`.
  The reconciler preserves and freezes either terminal status. HTTP schemas,
  OpenAPI and the database schema are unchanged.
- FAILED finalization stops local capture and presents an explicit incomplete
  result rather than navigating as if end succeeded.

This does not implement R4's complete replacement-socket ownership/capture
protocol or R5's end-of-input handshake. Frames captured but not submitted before
the server seals ingress are outside R3's drain boundary.

## Shared finalization and durable jobs

All end callers await one shielded task for that meeting. Cancelling an HTTP
caller does not cancel the drain; a later end request joins the same result.
One 20-second deadline covers sealing/consuming ingress, stopping streams,
flushing ASR tails, consuming their events, closing segments and retrying buffered
persistence. Stream stop cannot wait forever for a full failed-ASR queue.
Cancellation is awaited before closing files. Cooperative cleanup can add the
bounded adapter/socket close budget after the work deadline.

Only after drain succeeds does the completion transaction lock and refresh the
meeting, commit COMPLETED and enqueue the version-keyed intelligence job. A
concurrent caller sees the same committed result. Completion is broadcast after
commit. If drain or persistence fails, end records FAILED and enqueues no job.
The bounded persistence buffer remembers if it discarded anything; later recovery
cannot incorrectly certify that all final segments were saved.

On startup, **before starting the single in-process worker**, running intelligence
jobs are recovered. Matching durable outputs mark the job succeeded without
another provider call. Without outputs, attempts below the existing limit return
to pending; exhausted attempts become failed. This relies on one app process,
not distributed worker leases. An interrupted external request may still have
been billed if its response never reached durable storage.

## Test evidence

R3-specific suites:

- `tests/unit/test_r3_lifecycle.py`: open/push/reader/fatal/health failures,
  tail word delivery, flush failure, full-queue stop, bounded shared deadline,
  slow-peer fan-out, ingress rejection, concurrent and cancelled finalization.
- `tests/integration/test_r3_failure_lifecycle.py`: actual gateway + PostgreSQL,
  blocked opening alongside a healthy participant, exact PCM preservation,
  recovery epochs and one outage gap, disk failure isolation, simultaneous HTTP
  end, failed final persistence, bounded startup retries and committed-output reuse.
- `frontend/src/realtime/__tests__/client-status.test.ts`: participant-specific
  warning and immutable live gap status.

Validation uses explicitly fake ASR/LLM providers and isolated native PostgreSQL
14 on loopback port 55433. Docker Desktop remains manually paused. PostgreSQL 16
container parity is not claimed. Local WebSocket transport tests also run.

```sh
# backend/, after creating an isolated mosaique_test database
MOSAIQUE_ASR_RUNTIME=fake MOSAIQUE_LLM_PROVIDER=fake \
MOSAIQUE_TEST_DATABASE_URL=postgresql+asyncpg://mosaique@127.0.0.1:55433/mosaique_test \
uv run --no-sync pytest -q -m 'not slow'
# Same environment, separately: uv run --no-sync pytest -q -m slow
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
# frontend/
npm test -- --cache=false
npm run typecheck
npm run build
```

**Results:** 444 backend tests pass (one slow test deselected); the accelerated
hour passes separately in 68.63 seconds. The final targeted lifecycle/persistence
rerun passes 26 tests. Frontend: 93 tests, typecheck and build pass. Ruff check
and format check pass (155 files). Mypy retains the eight pre-existing MLX dependency/type errors; no new ones.
The exported OpenAPI document matches the committed frontend copy.

## Remaining acceptance and rollback

Real `moshi-server` interruption/recovery, CUDA tails, two-stream throughput,
browser-call tests and cross-network voice remain unverified. Run R2's hardware
probe first; then interrupt ASR during two real microphone streams and inspect
recorded bytes, gaps, fresh session epochs, peer continuity and end/review.
Azure quota/allocation and the reviewed region amendment are still prerequisites;
this slice allocates nothing.

No migration is required. Roll back app/frontend together to R2 with no active
meetings; that restores the documented failure and drain defects. Preserve DB
and audio for failed meetings. FAILED denotes an incomplete end result, and this
slice adds no automatic repair or offline transcription. Review/merge R3 before
R4 (participant identity and guest review); hardware acceptance stays open.
