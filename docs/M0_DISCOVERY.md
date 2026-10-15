# M0 discovery and technical evidence

Observed 15 October 2026 against application base
`7412d8d9b6cc66f928d4cf01a57d2a65b20127fb`. Source inspection is not runtime proof.
See [executed checks](reports/M0_BUILD_REPORT.md). Paths below are repository-relative.

## Preserve, adapt and retire matrix

| Actual module/files | Observed behavior | Proposal and preservation condition |
|---|---|---|
| `frontend/src/App.tsx`, `meeting/{MeetingList,JoinPage,LiveMeeting,ParticipantPanel}.tsx`, `styles.css` | React/Vite meeting list, join/live screens, roster, controls | Adapt navigation for account/workspace; preserve meeting controls, French UI and explicit empty/error states |
| `frontend/src/meeting/TokenGate.tsx`, `api/{client,credentials}.ts` | Manual host token and per-meeting session credentials | Replace with OIDC/cookie session; retain second-tab/credential separation behavior in tests |
| `frontend/src/review/{ReviewPage,evidence,highlight,paragraphs}.*`, `audio/playback.ts` | Evidence navigation, grouping/highlighting, corrections and audio playback | Reuse; coarse new ASR timestamps must not masquerade as precise word highlighting; recording remains optional |
| `frontend/src/audio/capture.ts`, `public/audio-worklet.js`, `realtime/{client,frames,buffer,silence,webrtc,roster,reconciler}.ts` | Separate PCM capture/transcript WS and custom peer media/signaling, buffered reconnect and reconciliation | Replace media/capture with LiveKit SDK after two-user parity tests; adapt transcript reconciliation, preserve gaps and reconnect states |
| `backend/src/mosaique/app/api/meetings.py` | Create/list/join/end, ICE configuration, transcript/search, output/regeneration, corrections and ranged audio | Keep observable contracts where possible; extract policy from handlers; retire ICE/signaling after LiveKit cutover |
| `app/auth/{tokens,authorize}.py`, `app/api/dependencies.py`, `app/seed.py` | HS256 host/participant tokens; org and meeting checks; seeded user, no complete login/membership flows | Replace credential mechanism and enrich policy. Preserve denial behavior, add current membership/revocation checks |
| `realtime/gateway/{endpoint,ingress,broadcaster}.py`, `protocol/{messages,frames}.py` | Authenticated hello, 3,849-byte framed PCM, scoped broadcast, keepalive, current-socket checks | Retire PCM/signaling protocol after new-path parity; replace with authorized durable transcript updates |
| `realtime/sessions/{meeting,participant,registry}.py`, `runtime_state.py` | Bounded participant queues, gap accounting, reconnect grace, stream pumps, finalization and persistence retry | Preserve testable semantics; replace orchestration with Pipecat ownership. Do not copy the large meeting runtime wholesale |
| `speech/interfaces`, `speech/adapters/{fake,kyutai}`, `asr_runtime/{factory,moshi_ws}.py` | Fake, local MLX and remote Moshi/Kyutai runtime selection, no silent fake fallback | Keep deterministic fakes and regression fixtures; retire old production ASR only after Voxtral parity. Wire formats are incompatible |
| `transcript/{segmenter,search,corrections}.py`, `domain/{state,ids,errors}.py` | State guards, segmentation, effective corrected values, search | Reuse core policy; segmenter assumes word timings not observed in Voxtral, so adapt rather than fabricate them |
| `persistence/models/tables.py`, repositories, migrations `0001`–`0003` | Eight core tables, tenant columns, original/corrected text, unique segment sequence, join nonce | Expand in place; keep IDs/raw transcript/history; account belongs to one org today |
| `intelligence/{schema,prompt,provider}.py`, `llm_runtime`, `jobs/processor.py` | Structured citations, fake/HTTP provider boundary, persisted retries and startup recovery | Reuse validation/provider concepts; add immutable snapshots, review state and leased jobs. No ticket connector exists |
| `speech/audio/store.py`, `app/api/ranges.py`, `observability/*` | Recording store seam, range handling, health/latency/logging | Preserve opt-in playback and health/degraded visibility; audit tenant keys, redact content and add worker/queue metrics |
| `docker-compose.yml`, backend/frontend Dockerfiles, `deploy/asr/*`, `deploy/turn/*` | PG16/app/frontend, legacy ASR and TURN deployment material | Keep local app/DB tooling; retire legacy ASR/TURN only after parity. Do not run deployment commands |
| `backend/tests/{unit,integration,realtime}`, `tools/replay/*`; frontend Vitest and `e2e/*` | Negative auth, lifecycle, corrections, replay, overlap/reconnect and browser scenarios | Preserve regression intent; port adapter-dependent tests; fixtures and lint setup need repair |

Existing tests do not prove enterprise acceptance. In particular, the prototype
has useful tenancy checks but lacks global accounts/multiple memberships and
approved external actions. API `authorize_meeting_access` accepts org-wide host
access, which is broader than proposed private-meeting access. Tenant columns do
not enforce cross-parent consistency: model FKs mostly reference IDs alone.
`AudioSessionRepository.finish` uses an unscoped primary-key lookup; future worker
authorization must not assume all repository operations already enforce tenancy.
`MeetingIntelligenceProcessor.recover_running` explicitly assumes a single process.
`validate_outputs` validates citation existence, not semantic support or owner IDs.
These are source-observed limitations, not reproduced exploit claims.

## Known baseline gaps and regressions to protect

- Unit suite after allowing localhost sockets: **326 pass, 13 fail, 9 skip**.
  Eleven failures need `docs/mosaique-b1-main/b1-report.json`; two need
  `docs/slice4-last-test-report.json`. Nine skips also depend on those reports.
  Restore only sanitized, licensed fixtures or replace with explicit synthetic
  regression data; never import customer recordings to make tests green.
- Mypy: eight MLX adapter attribute/export errors. Ruff passes. Frontend 115 tests,
  typecheck and build pass; lint fails because ESLint is absent from tooling.
- Contrast script reports 43 passing checked pairs and three acknowledged gap
  entries; a green script is not proof that all UI contrast issues are fixed.
- `test_l28_orphaned_final_word.py`, segmentation tests, flush/gap/reconnect and
  corrections tests encode prior failures worth preserving. Historical accuracy
  numbers in comments are not newly measured evidence.
- No GitHub Actions workflow found. Integration fixtures call `drop_all` and
  `TRUNCATE`; never point them at the existing app DB. Browser tests need running
  backend/frontend and a disposable database; Playwright config starts no servers.
- Pre-existing working-tree deletions: `CLAUDE.md`, `CODEX_HANDOFF.md`,
  `PROJECT_STATE.md`, `README.md`, and four `infra/azure/` files. Left unchanged
  and excluded from the M0 commit. Old ADR references in code are not accepted
  current decisions unless their sources are recovered and reviewed.

## Upstream inspection and dependency recommendation

Sources fetched on 15 October 2026; main/docs are mutable. No dependency installed
or runtime exercised for these findings.

| Component | Evidence | Recommendation / remaining gate |
|---|---|---|
| Pipecat | Release page resolves to [v1.12.0](https://github.com/pipecat-ai/pipecat/releases/tag/v1.12.0). Its [transport](https://raw.githubusercontent.com/pipecat-ai/pipecat/v1.12.0/src/pipecat/transports/livekit/transport.py) emits UserAudioRawFrame but lacks audio_in_user_tracks and uses one resampler | 1.12.0 is an inspected baseline, **not** an approved multi-user pin. Prefer a released version containing per-user fixes; otherwise review and pin an exact upstream commit before M2 implementation. Fetching main's SHA through GitHub failed in this investigation |
| Current Pipecat main | [Transport](https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/transports/livekit/transport.py) has audio_in_user_tracks, identity-tagged audio, per-user resamplers and stream cleanup. Still has an unbounded audio queue and publishes an audio output track during connect | Set per-user mode explicitly, disable conversational interruption semantics, audit every queue. Verify subscribe-only bot behavior: output-disabled does not by itself prove no publication. Prefer upstream fix over broad publishing permission |
| Pipecat lifecycle | [Pinned worker](https://raw.githubusercontent.com/pipecat-ai/pipecat/v1.12.0/src/pipecat/pipeline/worker.py) exposes PipelineWorker and Start/End/Cancel lifecycle; graceful End can wait indefinitely. [task.py](https://raw.githubusercontent.com/pipecat-ai/pipecat/v1.12.0/src/pipecat/pipeline/task.py) is a compatibility layer | Use upstream lifecycle with application drain deadlines and awaited cancellation; do not blindly follow old PipelineTask examples |
| LiveKit SDKs | [Pipecat 1.12.0 dependencies](https://raw.githubusercontent.com/pipecat-ai/pipecat/v1.12.0/pyproject.toml): livekit >=1.0.13,<2; livekit-api >=1.0.5,<2; pyjwt >=2.12,<3 | Python 3.12 fits repo; resolve and lock exact SDK versions in isolated media environment. Verify revoke_token_ts support in selected API SDK. Browser SDK exact pin remains M2 selection; no tested bundle claimed |
| LiveKit Cloud | [Token lifecycle](https://docs.livekit.io/frontends/reference/tokens-grants/) distinguishes join expiry, refreshed tokens and Cloud revocation | Room-scoped grants, explicit cutoff on removal, deny renewal in app; live two-account and revocation tests required |
| vLLM | [v0.31.0 connection source](https://raw.githubusercontent.com/vllm-project/vllm/v0.31.0/vllm/entrypoints/speech_to_text/realtime/connection.py) confirms handshake, PCM16 append, start/final commit, deltas and done; commit while generating is ignored; queue clears after done | Candidate v0.31.0 in separate image, lock digest/audio extras before build. New socket per rotation avoids unverified repeated-utterance races. No batching-performance claim |
| Model | [Pinned 2602 model card](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602/blob/2769294da9567371363522aac9bbcfdd19447add/README.md), plus local reference | Candidate mistralai/Voxtral-Mini-4B-Realtime-2602 revision 2769294da9567371363522aac9bbcfdd19447add. Reference Arabic model is not a validation of this model |
| Modal | Local reference pins 1.6.1; [Servers](https://modal.com/docs/guide/servers) separates soft target concurrency from hard max concurrency | Candidate modal==1.6.1; one L4/one container for approved experiment, min_containers=0, explicit admission cap. Concurrency setting is not GPU batching |

Pipecat [UserAudioRawFrame](https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/frames/frames.py)
carries user_id alongside audio, sample rate and channels; it does not establish
our admission generation or accurate meeting source-time mapping. The application
must supply that context. Main-source findings are recommendations, not release
guarantees. Dependency resolution, Linux import smoke tests and real track tests
are prerequisites to an implementation pin.

## Prior Voxtral project: safe local inspection

Read-only access to `/Users/mac/voxtral-ar-realtime` confirmed HEAD
`3dd4f96e22bf147a129e63b62f4fc18053458d1d`, matching MODAL_REFERENCE.md.
Read only `voxtral_rt/upstream.py`, `deploy/modal_app.py`, `docker/Dockerfile`
and commit metadata. Did not import or execute deployment code, open credentials,
audio or environment files, or copy reference source into this repository.

Observed: model validation then starting commit; base64 PCM16 appends; final commit
then done; idempotent finish; one-utterance client; image audio-extra check; CPU
weights download; supervised engine startup and shutdown; static gateway key;
one L4/container and soft concurrency target 16. Reuse those **patterns**, adapting
header authentication, deadlines, limits and session rotation. Prior 65 CPU tests,
~4m45s cold start, ~0.5s lag and memory numbers remain **inherited claims** from
[MODAL_REFERENCE.md](MODAL_REFERENCE.md), not rerun or independently measured here.
The reference's proposed meeting affinity is not automatic routing behavior;
initial one-container experiment needs no affinity service. Any later multi-container
policy needs separately tested routing/reservations.

## Approved-budget experiment specification (NOT RUN)

ASR-01..04, MEET-01, OPS-03. Explicit human cloud/budget permission is required
before provisioning, downloading to Modal or starting a GPU. Budget proposal:
one L4, max one container, at most four billed GPU-hours total including failed
boots and teardown, then stop. Obtain current GPU/CPU/memory/storage/egress prices
and a monetary ceiling before execution; historical $0.80/hour is not a quote.

1. Freeze image digest, dependency locks, model revision, region, flags, delay,
   chunk size and test-machine clock configuration. Import audio extras on CPU.
   Record model-download and GPU boot times separately; health must imply engine ready.
2. Paced, synthetic or explicitly licensed 16 kHz mono tracks with distinct phrases,
   ground-truth word/time annotations, French/English/Arabic coverage and deliberate
   overlap. Never customer recordings. Same fixture and parameters at 1, 2, 4 sessions.
3. One model process/GPU for all sockets. Three warm trials per concurrency, ten
   minutes each, then a 30-minute four-stream soak with proposed five-minute rotations.
   Stop early on OOM/unbounded lag; record failure rather than silently lowering load.
4. Record source end → delta-visible and source end → final-visible p50/p95,
   first text, drain time, WER/CER by language, attribution errors, lost/duplicate
   ranges, queue depth/age, throughput, GPU utilization/memory, KV usage and engine
   scheduler counters. Token rate alone is not transcript latency. Define samples
   and denominator, report per-stream fairness and worst stream as well as aggregate.
5. Repeat cold starts (three within budget); separate engine-only from full
   browser → LiveKit → Pipecat → Modal → saved transcript latency. Measure mute,
   simultaneous speech, track republish, participant leave, network loss, socket
   timeout, DB outage and worker/container termination. Verify no tasks/sockets or
   capacity reservations remain after teardown.
6. Demonstrate scheduler batching only if counters/traces show shared scheduling;
   concurrent sockets alone establish neither batching nor efficiency. Compare
   compute per audio-minute and lag slope. Report steady-state and cold/idle cost
   per participant-hour with actual billed duration, and all cost assumptions.

Proposed M2 decision thresholds: zero speaker cross-attribution or unexplained
gaps/duplicates; bounded queues and stable lag; p95 interim latency target ≤2 s
at two streams, measured four-stream result even if it fails; cleanup within ten
seconds after forced cancellation. Latency target misses require a reviewed
capacity/product decision, never relabeling an estimate as acceptance. Long-session
KV growth, context limits and rotation quality remain gating research questions.
