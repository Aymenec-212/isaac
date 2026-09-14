# MLX single-stream recovery — 2026-09-14

MLX remains limited to one active stream per process. The experimental
`allow_concurrent_streams` bypass is removed; do not re-enable it for phone/guest
testing. Use the separate serving runtime for concurrent transcription.

## Failure and correction

The meeting runtime bounds ASR close to one second. The old MLX close awaited a
worker join before releasing its global lock. Cancellation during that await
skipped release permanently, causing subsequent opens to report `MlxUnavailable`.
Startup failure/cancellation could also retain the lock. Releasing on the caller's
timeout instead would be unsafe: the old worker might still be using shared model
state.

The MLX worker now owns initialization, inference, and lock release in `finally`.
Cancelled start/close signals it to stop after its current operation. The slot
remains locked until the worker exits, then becomes reusable even if the awaiting
coroutine was cancelled. Pending queued audio is not replayed during teardown.
The constructor has no concurrency override.

The session liveness clock now starts when outstanding audio work arrives, not
while waiting for first audio or while idle. The five-second genuine-stall check
is retained; no timeout is hidden by simply raising its threshold.

## Verification

- Regression tests cover second-stream rejection, no bypass, idempotent release,
  cancelled close, cancelled initialization, initialization failure, and first
  audio after idle. The focused adapter/runtime/architecture selection passed
  70 tests.
- The full non-slow backend run had 469 passing tests and one failure in the
  pre-existing uncommitted `test_a_silent_participant_does_not_claim_the_recognizer_stream`.
  That test requests lazy session creation for observers, which the existing
  meeting lifecycle does not implement. It uses FakeRecognizer and is independent
  of this MLX lock fix; its source is left untouched. Do not infer that a second
  joined, non-streaming observer is guaranteed not to occupy the MLX slot.
- Real cached MLX weights, offline, ran two sequential meetings through the
  actual ASGI gateway, segmenter, and isolated PostgreSQL. Each joined quietly
  for six seconds before receiving generated French speech at real time.
- Both meetings emitted live transcript messages and persisted recognizable
  French text starting “Bonjour à tous, nous allons préparer la réunion de
  demain”. Neither produced ASR errors, unavailable status, or gap segments.
- This is synthetic speech through the real model, not a fake recognizer or a
  silence-only frame counter test. It does not certify a particular physical
  microphone or concurrent MLX usage.

The real-speech regression is retained as
`backend/tests/integration/test_mlx_speech_opt_in.py`. It is skipped by default.
Set `MOSAIQUE_MLX_TEST_WAV` to a mono, signed-16-bit, 24 kHz French WAV beginning
with “Bonjour”, and run that file with `HF_HUB_OFFLINE=1`. Set both
`MOSAIQUE_DATABASE_URL` and `MOSAIQUE_TEST_DATABASE_URL` to an **isolated disposable
database**: the test fixtures recreate tables. The test never needs a hosted LLM.

The installed MLX/moshi package stubs still cause eight mypy attribute/export
errors on pre-existing model-loader calls; these are not runtime inference errors.
Ruff and the targeted behavioral tests pass.

Restart the backend process after applying this fix: a process already holding
the old leaked lock cannot be repaired by editing the source on disk. Start one
backend worker, with `MOSAIQUE_ASR_RUNTIME=mlx`, and only one active microphone.
No frontend redesign files, dependency pins, or existing meeting data are changed.
