# R2 — remote ASR protocol and validation harness

Baseline: R1 merged in PR #20, `6f4cf1d`. Status: adapter changes and validation
tooling implemented; **real NVIDIA acceptance remains unverified**. This PR
allocates no resources and does not change the deployment region.

## Observable changes

The remote provider selected by `build_recognizer` now uses
`RemoteKyutaiRecognizer`, which remains a `KyutaiRecognizer` and satisfies
`StreamingRecognizer`. Meeting, domain, transcript and MLX code are unchanged.

- Opening a session waits up to five seconds for `Ready`. The pinned server's
  `Error: no free channels` becomes `ASR_CAPACITY_EXHAUSTED`; it is distinct from
  transport, protocol and runtime failures. Failed or cancelled opens close.
- `Step.prs[2]` is the two-second pause head (four heads: 0.5/1/2/3 seconds).
  The previous last-element and arbitrary-key heuristic is removed. Invalid
  probabilities do not manufacture boundaries. Threshold tuning remains deferred.
- Count this channel's Step messages; the wire `step_idx` is global across the
  batch. The R1 config's six-token delay is **480 ms**, not a rounded 500 ms.
  Word/EndWord times are already stream-relative and are not shifted again.
- Terminal flush sends a unique matching marker, then ten seconds of synthetic
  silence without real-time sleeps, following the upstream file path. Four
  seconds bounds send/wait inside the runtime's existing five-second deadline.
  A wrong marker cannot finish flush or release a pending word. Timeout is a
  fatal error, not logged success. Flush closes its socket on success/failure/
  cancellation. Synthetic frames do not advance transcript time beyond input.
- Reader/send failure terminates the session and releases its connection.
  **No reconnect/replay inside the same backend.** Reconnecting Rust resets
  inference state; reusing its old counters would corrupt timestamps. R3 owns
  recovery into a new audio/inference session and the user-visible warning/gap.
  The remote session reports unhealthy after closure; no change to MLX health.
- Idle readiness uses Ready + silence inference progress + matching marker,
  caches the result for three seconds and releases the probe slot. The probe has
  a 1.5-second work budget plus bounded socket cleanup inside the HTTP health
  endpoint's three-second guard. Admission and
  probing share a lock. With active sessions, readiness uses observed recent
  progress and local slot counts instead of opening another connection. Two
  occupied slots report not-ready for additional admission. No-progress sessions
  report not-ready. This assumes one app process and exclusive ownership of the
  two-slot server; it is not a distributed capacity allocator.
- Transport uses MessagePack float32, bounded WebSocket receive buffering and
  open/close deadlines; malformed messages become transport failures. The ASR
  key stays in the header, and connection errors omit endpoint detail.

New files are restricted to the Kyutai adapter, tests and opt-in tooling; no API
or DB schema changes, OpenAPI regeneration, segmentation retuning or L-28 fix.
R3's neutral failure/lifecycle work is still necessary: an adapter error alone
does not prove the meeting survives an ASR outage or presents correct status.

## Protocol evidence and limits

The target remains moshi source
[`e6a55d2722a65870ef52a6c9f6ecfc0e90f38362`](https://github.com/kyutai-labs/moshi/tree/e6a55d2722a65870ef52a6c9f6ecfc0e90f38362/rust)
and the R1 STT-1B model lock. Review `moshi-server/src/batched_asr.rs` for Ready,
capacity, per-active-channel Step dispatch and marker/silence drain;
`moshi-core/src/asr.rs` for global vs per-stream counters. The upstream
[microphone client](https://github.com/kyutai-labs/delayed-streams-modeling/blob/main/scripts/stt_from_mic_rust_server.py)
explicitly names VAD head index 2. Sources inspected 2026-09-12.

These observations inform tests but are **not** a hardware compatibility claim.
In particular, real tail completion within four seconds, T4 F16 kernels, VAD
quality, throughput, memory and repeated-meeting stability remain GPU gates.

## Run the real-server gate

Use a verified R1 image/host first. The deployment must actually use batch two,
the pinned revisions and F16 LM. Export `MOSAIQUE_ASR_MOSHI_SERVER_API_KEY` through
protected local configuration; never pass the key on the command line or in URL.
For the application also set `MOSAIQUE_ASR_MOSHI_SERVER_QUANTIZATION=f16`; the
existing application default remains BF16 for compatibility with other deployments.

Prepare two distinct consenting French speech fixtures as headerless 24 kHz
mono s16le PCM, with reference text and known final phrases. The tool pads only
the final partial 80-ms frame. The operator supplies sanitized provenance JSON:

```json
{
  "image_digest": "registry/image@sha256:REPLACE_WITH_ACTUAL_64_HEX_DIGEST",
  "moshi_revision": "e6a55d2722a65870ef52a6c9f6ecfc0e90f38362",
  "model_revision": "095e38f6242006a93c2541149b181988397f5c7c",
  "gpu": "T4; record actual device/VRAM",
  "driver": "record actual nvidia-smi version",
  "lm_dtype": "f16"
}
```

From `backend/`:

```sh
uv pip install -e '.[moshi-server]'
uv run --no-sync python -m tools.remote_asr \
  --url ws://127.0.0.1:8080 \
  --pcm-a /tmp/speaker-a.pcm --pcm-b /tmp/speaker-b.pcm \
  --tail-a 'reference final phrase A' --tail-b 'reference final phrase B' \
  --deployment-record /tmp/deployment-record.json \
  --report /tmp/r2-gpu-report.json
```

The endpoint must be private or tunneled. The harness opens two sessions, verifies
third-slot rejection, concurrently feeds both fixtures at 1x, drains and checks
both reference tails, then opens a released slot and verifies fresh progress.
It reports hashes of the padded PCM actually sent, words/times, input/processed frames, peak frame lag,
elapsed/drain times and a bounded provenance field set. Failures yield a failed
JSON report and nonzero exit. Reports contain fixture transcripts: keep them
local until consent/review permits committing them. No real report was produced
by this PR. Simulated harness tests are explicitly labeled simulated.

A passing harness is one R2 gate, not the full two-user meeting acceptance:
inspect words/timings against references, measure GPU baseline/load/release
memory and sustained lag, record process/image/config checksums, run real ASR
stop/restart and repeated slot reuse. It does not measure browser-visible
latency, WebRTC voice, cross-network call quality or persisted Slice 5 outputs.
R7 retains those requirements.

## Azure region investigation — 2026-09-12

`az vm list-skus --resource-type virtualMachines --size Standard_NC4as_T4_v3
--all` was read across regions. The following EU candidates report **no listed
T4 subscription restriction**. This is weaker than allocatable capacity.

| Candidate | Public Linux T4 rate / hour | Observation |
|---|---:|---|
| France Central | $0.615 | No SKU restriction; filtered GPU/total-core usage returns `[]` |
| Spain Central | $0.684 | No SKU restriction; filtered GPU/total-core usage returns `[]` |
| Italy North | $0.615 | No SKU restriction; quota not checked |
| Poland Central | $0.656 | No SKU restriction; quota not checked |
| Sweden Central | $0.558 | No SKU restriction; quota not checked |

France Central is the first nearby EU candidate to pursue; Sweden Central is a
lower-compute-cost alternative. Prices are from the
[Azure retail API](https://prices.azure.com/api/retail/prices), filtered by each
region, `Standard_NC4as_T4_v3`, Consumption, Linux regular (no Spot/Low Priority).
These are compute-only list rates; app/disk/IP/network totals and credit coverage
must be repriced for a chosen region. West Europe, North Europe, Germany West
Central and UK South still have a T4 location restriction for this subscription.

**Remaining blocker:** an unrestricted SKU listing plus empty usage is not
positive quota evidence. Confirm the intended subscription's GPU-family and
regional-core limits, credit balance/expiry and actual allocation eligibility.
Then review a concrete region/price/parameters amendment to R1's West-Europe-only
Bicep before provisioning. No billing upgrade, region switch or resource creation
was performed here.

## Validation and rollout

- Backend unit suite, including actual localhost WebSocket/MessagePack peers:
  `uv run --no-sync pytest -q -m 'not integration and not slow'` — **329 passed,
  94 deselected**. Scripted protocol tests cover Ready/capacity, wrong marker,
  tail timeout/cancellation, global counters, VAD head, reader failure, cache,
  occupied slots and reuse. Harness tests require both reference tails.
- `uv run --no-sync ruff check .`: pass. No new mypy errors: the full run still
  reports the same eight pre-existing MLX export/type errors (100 source files).
- The existing `moshi-server` extra was installed locally to execute the socket
  tests (`msgpack 1.2.2`); no dependency declaration or lockfile changed.
- Frontend: 91 unit tests pass; typecheck and production build pass. Backend
  format check passes (153 files); probe CLI help
  and local document links pass.
- No GPU inference, Docker image build, cloud deployment, database integration,
  slow test or browser-call acceptance was run. Fake/localhost tests do not
  close the real-server gate.

Deploy only with no active meeting once real GPU validation passes. No migration
is needed. Roll back the application revision to R1 if necessary, but that also
restores unknown remote readiness and unsafe/unverified reconnect/flush behavior;
do not admit real meetings under that rollback. MLX/fake remain local options.
Review/merge this PR before R3; keep GPU acceptance explicitly open until an
actual report meets the gate. The broader milestone remains unverified.
