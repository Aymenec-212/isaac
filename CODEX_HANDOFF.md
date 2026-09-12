# CODEX_HANDOFF.md

> **Current amendment — 2026-09-12:** [Two-user voice / Azure ASR architecture](docs/two-user-cloud-architecture.md)
> records the maintainer's new priority and supersedes companion-only D-01/ADR-01,
> the WebRTC exclusion and older single-user-first sequencing where they conflict.
> Direct WebRTC/TURN carries voice; the existing PCM WebSocket and ASR seams remain.
> Work proceeds one slice, one documented PR, review/merge, then the next slice.
> R0 is documentation only; deployment review is pending and no new feature or
> infrastructure is claimed implemented. Historical text below retains its original
> evidence; use the root PROJECT_STATE.md and the R0 sequence for current next work.

**Mosaïque — realtime meeting intelligence, French-first, for French SMBs.**

Handoff written 2026-09-11, against `main` at commit `74c7ca6`.

---

## 0. How to read this document

This describes the repository **as it actually exists**, not as the design
documents intend it. Where the two differ, this file follows the code.

**It is not exhaustive, and it will go stale.** Before proposing any
infrastructure change — a new runtime, a deployment topology, a schema
migration, a transport swap — read the repository and the architectural
documents yourself. Specifically:

| Read | For |
|---|---|
| `PROJECT_STATE.md` | **Reality.** The authoritative record of what exists, what is verified, what is a guess. Longer and more current than this file. Start at §12. |
| `CLAUDE.md` | The working agreement: non-negotiables, known traps, decisions that must not be re-litigated. |
| `docs/mosaique-prototype-technical-spec.md` | **Normative.** Contracts, schemas, thresholds, the §14.1 failure matrix. |
| `docs/mosaique-implementation-blueprint.md` | Reconciles contradictions between sources; wins only where sources conflict. |
| `docs/IMPLEMENTATION_PLAN.md` | Slices and exit gates. v1.4. |
| `docs/ADR-013-mlx-development-runtime.md` | The only ADR written as a file. Read it before touching the ASR runtime. |
| `docs/mosaique-future-media-plane-options.md` | **NON-NORMATIVE.** Governs nothing. Do not let it widen prototype scope. |

Precedence when they disagree: **reality beats intent, spec beats blueprint,
blueprint beats the rest.**

`README.md` is **stale** — it still says "Status: Slice 2". Its bootstrap
instructions are current; its status claims are not.

---

## 1. Current product capabilities

What a person can actually do today, on one machine:

- A host authenticates by pasting a seeded host token (stands in for login —
  L-11) and creates a meeting. An invite link is produced.
- Participants open that link in their own browser, give a display name, and
  join. Each browser captures its own microphone through an AudioWorklet,
  resamples 48 kHz → 24 kHz, and streams 80 ms PCM frames over a WebSocket.
- Speech is transcribed live. Interim text updates word by word; finalized
  segments are attributed to the speaker and ordered across participants on one
  shared meeting timeline.
- A participant panel shows who is in the room and who is currently speaking.
- Reconnect, pause/resume, idle close, overload and degraded-persistence
  behaviour are all implemented and tested.
- Ending the meeting finalizes the transcript, then asynchronously produces a
  **summary, decisions and action items**, each citing real transcript segment
  ids.
- The review page renders the finalized transcript as readable **speaker-turn
  paragraphs** (not one paragraph per segment), with an mm:ss timestamp per
  turn. Citations are clickable and seek the stored audio. `?q=` search is
  accent-insensitive and highlights the matching phrase in place.
- Transcript segments can be **corrected** — text and speaker — additively.
  Correcting bumps `transcript_version`; the summary then declares itself *à
  revoir* and offers one **Régénérer** button. Regeneration is never automatic.
- A health banner reports dependency state and **blocks meeting creation** when
  the ASR runtime or database is down.

Everything above has run end to end on Apple silicon against **real MLX Kyutai
STT + OpenAI `gpt-4o-mini`**. It is a **one-participant** product on that path:
see §8.

---

## 2. Repository layout and entry points

```
backend/
  src/mosaique/
    app/main.py                  # create_app() — the ASGI factory, THE entry point
    app/seed.py                  # `python -m mosaique.app.seed` → prints a host token
    app/api/meetings.py          # all /meetings routes
    app/api/health.py            # /livez, /readyz, /health/deps
    app/api/schemas.py           # request/response models (OpenAPI source of truth)
    app/auth/                    # host + session token minting and authorization
    config/settings.py           # every knob; nothing else reads os.environ
    domain/                      # state machine, ids, error envelope — no I/O
    realtime/
      gateway/endpoint.py        # the WebSocket endpoint (FastAPI lives HERE and nowhere downstream)
      gateway/ingress.py         # BrowserWebSocketIngress — the only MeetingIngress impl
      gateway/broadcaster.py     # fan-out to connected sockets
      ingress/interfaces.py      # the D-04 seam
      sessions/meeting.py        # meeting runtime: one ASR session per participant stream
      sessions/participant.py    # per-participant timeline (ADR-11), frame pump
      protocol/messages.py       # the WS message vocabulary
      protocol/frames.py         # binary frame codec
    speech/
      interfaces/asr.py          # StreamingRecognizer / ASRSession — the ASR seam
      adapters/fake/             # FakeRecognizer, MeasuredRecognizer
      adapters/kyutai/backend.py # KyutaiBackend Protocol (ADR-13)
      adapters/kyutai/mlx_runtime.py    # the ONLY module allowed to import a model library
      adapters/kyutai/moshi_server.py   # the deployment runtime — never run against a real server
      audio/store.py             # raw per-participant PCM (ADR-06)
    transcript/segmenter.py      # words → interim/final segments; pure, clockless
    transcript/corrections.py    # the single definition of "what this segment says"
    transcript/search.py         # accent-insensitive, in-Python, meeting-scoped
    intelligence/                # prompt, schema, provider + openai_chat adapter
    llm_runtime/ , asr_runtime/  # where the sockets live; vendor clients confined here
    jobs/processor.py            # the async meeting-intelligence worker
    persistence/                 # SQLAlchemy models, repositories, Alembic migrations
  tools/replay/                  # the replay harness (drives real WebSockets)
  tools/spike_b1/                # MLX probe — written, needs Apple silicon
  tools/export_openapi.py        # regenerates frontend/openapi.json
  tests/{unit,integration,realtime}/
frontend/
  public/audio-worklet.js        # capture + resample, runs off the main thread
  src/audio/capture.ts           # worklet wiring
  src/realtime/client.ts         # WS client, reconnect, bounded buffer
  src/realtime/reconciler.ts     # interim/final merge
  src/review/ReviewPage.tsx      # transcript, search, citations, corrections
  src/review/paragraphs.ts       # speaker-turn grouping
  src/health/ReadinessProvider.tsx  # ONE readiness poll, shared (see L-35)
  e2e/                           # Playwright specs
docker-compose.yml               # postgres + app-server + frontend
```

**Entry points:** `mosaique.app.main:create_app` (ASGI factory, `--factory`),
`python -m mosaique.app.seed`, `python -m tools.replay`, `alembic upgrade head`.

---

## 3. Architecture and module boundaries

Four logical runtimes in one process today (ADR-09, separable later): HTTP API,
realtime gateway, ASR adapter, job processor.

### The seams are enforced by a test, not by convention

`backend/tests/unit/test_architecture.py` parses the source and fails the build
on any violation. **If a change needs one of these imports to move, the design
is wrong, not the test.**

| Rule | Enforced over |
|---|---|
| No `fastapi` / `starlette` / `websockets` / `uvicorn` import | `domain`, `transcript`, `intelligence`, `persistence`, `jobs`, `speech`, `realtime/sessions`, `realtime/ingress` |
| No model library (`mlx`, `moshi_mlx`, `torch`, `transformers`, `sentencepiece`, `huggingface_hub`, …) | anything outside `speech/adapters/kyutai/` |
| No HTTP client (`httpx`, `openai`, `requests`, `aiohttp`) | the `intelligence` layer — the adapter must be reachable without its transport |
| The ASR adapter opens no socket of its own | `speech/adapters/kyutai/` |
| MLX deps stay an optional extra behind a platform marker | `pyproject.toml` |
| The default install pulls in no model library | `pyproject.toml` |

### The three seams that matter most

1. **`MeetingIngress`** (blueprint D-04, `realtime/ingress/interfaces.py`) — the
   runtime must not know where audio came from. One implementation today,
   `BrowserWebSocketIngress`. An SFU or platform ingress replaces it without the
   meeting, transcript or intelligence layers changing.
2. **`StreamingRecognizer`** (tech spec §9.1, `speech/interfaces/asr.py`) —
   `FakeRecognizer` and Kyutai are interchangeable. See §6.
3. **`KyutaiBackend`** (ADR-13, `speech/adapters/kyutai/backend.py`) — the model
   is fixed; `mlx` and `moshi_server` are two ways of running it.

**Providers are configuration, not architecture — both axes.** `asr_runtime`
(`fake`/`mlx`/`moshi_server`) and `llm_provider` (`fake`/`openai`) both default
to `fake` and both **fail fast at startup** on a missing key or URL rather than
silently downgrading. A silent fallback to a fake is the failure both guard
against: scripted French in a real transcript, or an invented decision in a real
summary, with only `asr_version` / `llm_model` to show for it afterwards.

---

## 4. Realtime / WebSocket architecture

One socket per participant: `GET /ws/meetings/{meeting_id}` (see
`realtime/gateway/endpoint.py`).

**Handshake and frames.** The client sends `hello` carrying its session token;
the server replies `hello.ok` or closes with 1008. Audio then flows as **binary
frames**: 80 ms of 24 kHz signed 16-bit mono PCM, 3840 bytes payload, with a
sequence number (`realtime/protocol/frames.py`). Constants live once in
`speech/interfaces/asr.py`.

**Server → client message types** (`realtime/protocol/messages.py`):
`hello.ok`, `transcript.delta`, `transcript.segment.final`,
`participant.joined` / `.left` / `.reconnecting`, `participant.speaking`,
`stream.status`, `meeting.state`, `meeting.outputs.ready`, `error`, `ping`,
`pong`.

**Liveness.** The server pings and hangs up after 30 s of silence (§7.4). This
is correct behaviour and has bitten the harness twice — see "Known traps" in
`CLAUDE.md`: never hold a socket open while doing slow work; generate audio
first, connect second.

**Reconnect.** Bounded client-side buffer plus sequence resume, with a 30 s
grace. The reconnect grace and the idle close are both 30 s and can race (L-21).

**Concurrency shape.** Every participant runs its own pump task against shared
runtime objects. **Anything mutated across an `await` needs a lock** — the
persistence buffer did not have one and silently dropped an already-broadcast
segment (A-15). This is the single most expensive class of bug this codebase has
found.

---

## 5. Transcript, finalization and meeting-intelligence flow

```
browser worklet ──80 ms PCM──▶ WS gateway ──▶ MeetingIngress ──▶ meeting runtime
                                                                      │
                                              one ASRSession per participant stream
                                                                      │
                                                   WordEvent / EndOfTurnEvent
                                                                      │
                                                              Segmenter (pure)
                                                        ┌─────────────┴─────────────┐
                                                  interim (memory)            final (DB)
                                                        │                          │
                                                 transcript.delta       transcript.segment.final
```

**Timeline rule (ADR-11 / blueprint D-02).** Meeting time is derived from
**frame counts** with silence padding, never from client clocks. Silence is
judged in **stream time**, never wall time — audio arrives faster than real time
in every replay, and comparing the two fabricates segment breaks. This bug has
been introduced twice. Do not reintroduce it.

**Segment closing rules**, in order (`transcript/segmenter.py`, spec §9.3 as
amended by Spike B1): sentence-final punctuation → duration cap →
`EndOfTurnEvent` above threshold → silence in stream time → `flush()`.
The punctuation rule exists because §9.3's *primary* rule (end-of-turn) is dead
code on MLX, which carries no VAD heads.

**Only final segments are persisted (ADR-05).** Interim text lives in memory and
is disposable. Process memory is never the authoritative record.

**Finalization.** `POST /meetings/{id}/end` → `FINALIZING`: drain the
recognizers, flush pending tails, write `asr_version`, close audio sessions,
enqueue exactly one intelligence job, then `COMPLETED`. Startup recovery
completes a meeting stranded in `FINALIZING`.

**Intelligence.** `jobs/processor.py` (`PROCESSOR_VERSION = "summarizer-v1"`,
3 attempts with backoff) builds the prompt from finalized segments, calls the
provider under a strict JSON schema, and **validates every
`evidence_segment_id` against real segments** before persisting. Outputs are
versioned and record which `transcript_version` they came from.
`meeting.outputs.ready` is pushed to any socket still open.

**Corrections (Q9, additive only).** `text` and `words` are **never written
again**. A correction lands in `corrected_text` / `corrected_participant_id` /
`corrected_at` / `corrected_by` (migration `0002`). Every reader — review page,
`?q=` search, **and the summarizer prompt** — goes through
`transcript/corrections.py`, which is the only definition of what a segment
says. It lives in `transcript/` rather than beside the API because `jobs/` and
`intelligence/` may not import a transport.

> Why additive matters beyond tidiness: destructive editing would make L-28, the
> 1.43% WER and every `[measure]` row unfalsifiable after the fact — you could no
> longer tell a model error from a human edit.

---

## 6. The MLX / Kyutai runtime arrangement

**The model is fixed** (`kyutai/stt-1b-en_fr`); **the runtime is a config axis**
(ADR-13). Three values of `MOSAIQUE_ASR_RUNTIME`:

| Runtime | What it is | State |
|---|---|---|
| `fake` | `FakeRecognizer`, and `MeasuredRecognizer` which replays *real* MLX emission timing (p50 320 ms, p95 1 280 ms, max 24 s between words) without a model | Default. Everything the automated suite runs on. |
| `mlx` | Kyutai STT on MLX, **in-process, on a worker thread** (`mlx_runtime.py`) | The development and measurement runtime. Requires Apple silicon. |
| `moshi_server` | Kyutai STT served by `moshi-server` over a WebSocket (`moshi_server.py` + `asr_runtime/moshi_ws.py`) | **The deployment runtime. Never run against a real server.** Needs a CUDA host. |

### `StreamingRecognizer` — what it is for

`speech/interfaces/asr.py` is the **only vocabulary** the rest of the
application speaks about speech recognition. It is what let `FakeRecognizer`
carry Slices 1–3 and real Kyutai arrive in Slice 4 without the runtime changing.
Two members exist specifically because a silently-defaulted capability is a trap
(L-25):

- `emits_end_of_turn` — declared, never discovered with `getattr`. A recognizer
  wrongly reported as silent gets a fallback segmentation rule it does not need,
  and its segments close in different places.
- `readiness()` — three states (`ready` / `not_ready` / `unknown`), no default.
  The tempting default, "ready", is the one that turns a broken runtime into a
  green health check.

Also on the interface: `transcribed_offset_ms` (how far the model has actually
transcribed, *not* how much audio was pushed) and `identity` (written to
`Meeting.asr_version` by the runtime, which is not allowed to know which adapter
it holds).

### The intended `moshi-server` / CUDA path

`moshi_server.py` already implements the wire protocol (`Audio` / `Marker` out;
`Step` / `Word` / `EndWord` / `Marker` back) behind the same `KyutaiBackend`
Protocol, with the translation, reconnect schedule and health arithmetic tested
against a fake transport. Two differences from MLX change what the segmenter can
rely on:

- Words arrive **whole**, with a start time, and `EndWord` gives a real
  `end_ms` — no piece reassembly, no inferred end.
- `Step` carries a **VAD signal**, so `EndOfTurnEvent` exists and §9.3's
  `end_of_turn_threshold` stops being dead code. This is also where it first
  becomes *measurable*.
- `Marker` is blueprint D-05's flush trick expressed in the protocol.

**Switching to it must remain a config change.** `MOSAIQUE_ASR_RUNTIME=moshi_server`
plus a URL. If swapping the backend would require touching the meeting,
transcript or realtime layers, the seam has been broken — and that is the
finding, not an inconvenience.

---

## 7. MLX limitations — read before planning multi-user

**MLX cannot serve the intended concurrent multi-participant path. This is not a
tuning problem.**

1. **One stream at a time, per process — enforced in code.** `LmGen` holds the
   per-stream KV cache while the weights are shared, so two concurrent MLX
   sessions would interleave caches and **corrupt both transcripts with nothing
   logged**. Rather than risk that, `MlxBackend.start()` refuses a second
   session outright:

   > `the MLX runtime serves one stream at a time in this process; a second participant would interleave KV caches and corrupt both transcripts. Use MOSAIQUE_ASR_RUNTIME=moshi_server for concurrent streams (A-3).`

   (`mlx_runtime.py`, guarded by a module-level `threading.Lock`.) This is L-26,
   and it is the hard gate on Phase C.
2. **No VAD heads.** The `-mlx` weights carry none, so `EndOfTurnEvent` never
   fires and §9.3's primary closing rule is dead code on this runtime. The
   punctuation rule exists to compensate.
3. **1.24x realised throughput**, p50 59.4 ms per 80 ms step. There is no
   headroom. Blueprint D-05's flush trick assumes several times real time, so
   **A-12 is answered negatively for MLX**: `flush()` pushes silence and waits,
   and segment-close latency reverts to the ~500 ms model delay.
4. **284 s cold model load**, which is why the app-server preloads weights at
   startup instead of inside the first meeting.
5. **Inference blocks**, so the model runs on a dedicated worker thread and
   events return via `call_soon_threadsafe`. Running it on the event loop would
   stall every other participant for three quarters of every frame interval.
6. **Docker cannot reach Metal on macOS** (ADR-13 consequence 1), so local
   development on a Mac is three containers plus one native host process.
7. **Every §8 number measured on MLX describes bf16-on-Apple-silicon, not
   production** (A-16). A number measured on MLX does not describe CUDA.

---

## 8. What each completed slice implemented

| Slice | Delivered | Status |
|---|---|---|
| **0** | Repo on `uv`; migration `0001` (eight tables); `POST/GET /meetings`; `/livez`; React app with an OpenAPI-generated typed client | VERIFIED |
| **1** | The whole spine on fakes: WS gateway, `MeetingIngress` seam, `ParticipantSession` with the ADR-11 timeline, pure segmenter, evidence-validated intelligence, job processor with retries, browser UI (worklet, WS client, reconciler, join/live/review) | VERIFIED |
| **2** | Two participants; `tools/replay` driving N streams over real sockets at a chosen speed; roster and speaking derived from ingress events only; per-speaker attribution and cross-participant ordering | VERIFIED |
| **3** | Failure behaviour: reconnect grace with sequence resume, ping/pong and stale-socket detection, pause/resume and idle close, the §8.4 overload policy with gap segments and `stream.status`, segment buffering when the database is unreachable, graceful drain | VERIFIED |
| **4** | Real Kyutai behind `StreamingRecognizer`: the adapter with `mlx` and `moshi_server` backends selected by typed config, bounded reconnect, `health()`, latency decomposition. Thresholds retuned against real French | VERIFIED on M1 + MLX |
| **5** | Real meeting intelligence: OpenAI adapter (wire format, no vendor SDK), strict structured outputs, `llm_runtime/` for the socket, FR-11 audio playback with Range requests, evidence links | VERIFIED (fake); real provider confirmed working, numbers unmeasured (L-31) |
| **6A** | Health endpoints that name the broken dependency; transcript search (FR-10); A-14 under real emission timing; the full-lifecycle test; degraded-state UX | 5 of 6 done — **§15 metrics remain** |
| **6R** | Readable transcript: speaker-turn paragraphs, colour-independent interim marker, distinct failed/thin summary states, clickable citations and search highlighting held as regression constraints, and **additive segment corrections** with a version handshake and a regenerate button | COMPLETE, validated on M1 |
| **6B** | `moshi-server` on a GPU host; measure the production serving path | **NOT STARTED — blocked on hardware** |
| **6C** | Four participants | **NOT STARTED — blocked on 6B** |
| **7** | Pilot hardening: magic-link auth, rate limits, retention job, security checklist, the eleven ADR files | NOT STARTED |

---

## 9. Verified vs implemented-but-unverified

`PROJECT_STATE.md` §0 carries the full vocabulary. **"Verified" requires named
test evidence (D-03). A passing demo is not evidence.**

| Mark | Means |
|---|---|
| ✅ **M1 + MLX** | Proven on Apple silicon against the real MLX Kyutai runtime. Says nothing about CUDA, `moshi-server`, or more than one concurrent stream. |
| ✅ **fake** | Proven by an automated test on `FakeRecognizer` / `FakeLLMProvider`. The seam is proven; the model is not. |
| ⚠ | Code merged, plausibly correct, no run behind it. Do not cite as evidence. |
| ❌ | Cannot be validated on any hardware this project currently has. |

**✅ fake** — everything the 516-test suite covers, including `MeasuredRecognizer`.

**✅ M1 + MLX** — the Slice 4 transcription run (1.43% WER, p95 first-word
1 934 ms, `docs/slice4-last-test-report.json`); `/readyz` against real weights;
and the manual end-to-end meetings of 2026-09-08 and 2026-09-10, the second
covering Slice 6R's grouped transcript and the correction path on a real French
transcript.

**⚠ implemented, not validated** — Slice 5's schema-rejection rate and cost per
meeting; the `moshi_server` backend's behaviour against an actual server.

**❌ needs NVIDIA + `moshi-server`** — A-3 (concurrent streams), A-4 (GPU
capacity), A-16 (do MLX and CUDA transcripts agree?), the GPU half of A-9,
`EndOfTurnEvent`, and §9.3's `end_of_turn_threshold`.

**❌ needs cross-network** — A-8. **Every run so far is loopback on one
machine.**

Two caveats worth carrying forward:

- **L-34** — the lifecycle chain has an automated walk (✅ fake) and a manual one
  (✅ M1 + MLX) and they are not the same walk. Read both halves together.
- **L-41** — the real-runtime correction pass is **attested, not recorded**. No
  artefact, nothing re-runs it, and it does not itemize which correction
  behaviours were exercised — notably whether **Régénérer** was pressed against
  the real provider. Do not cite "validated on M1" for anything narrower than
  "it works".

> **Never mark the production GPU serving path verified until it has actually
> served a meeting.**

---

## 10. Test counts and how to run them

**508 tests run by default** (509 exist; one is `slow` and deselected), all
green as of 2026-09-10 on both a Linux sandbox and the maintainer's M1 — which
is the only cross-check that exists, because **there is no CI** (L-18).

> ⚠ `PROJECT_STATE.md` §1 and `CLAUDE.md` both print **516** as the headline
> total. That figure does not reconcile with its own breakdown
> (305 + 93 + 91 + 19 = 508), and the same drift is visible in earlier revisions.
> The per-suite numbers below were re-counted by running the suites on
> 2026-09-11 and are correct; the 516 is not. Trust the commands, not the
> headline.

| Suite | Count | Needs |
|---|---|---|
| `backend/tests/unit/` | 301 | nothing |
| `backend/tests/integration/` | 73 | real PostgreSQL |
| `backend/tests/realtime/` | 25 (21 marked `integration`; 1 marked `slow`, deselected by default) | real PostgreSQL |
| **backend default run** | **398 passed, 1 deselected** | PostgreSQL |
| `frontend` vitest | 91 across 9 files | nothing |
| `frontend/e2e` Playwright | 19 specs across 5 files | a running backend **and** frontend |

```bash
# backend (from backend/)
uv venv && uv pip install -e ".[dev]"          # uv, never pip — including in Dockerfiles
uv run alembic upgrade head
uv run python -m mosaique.app.seed             # prints a host token
uv run uvicorn mosaique.app.main:create_app --factory --reload --port 8000

uv run pytest -q                               # 398 passed, 1 deselected
uv run pytest -q -m "not integration"          # 305, no database needed
uv run pytest -q -m slow                       # the accelerated hour, ~70 s
uv run ruff check . && uv run ruff format .
uv run mypy                                    # strict, 99 source files
uv run python tools/export_openapi.py ../frontend/openapi.json

# replay harness (from backend/, against a running server)
uv run python -m tools.replay run tools/replay/scenarios/two-participants.json \
  --host-token "$(uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')" --speed 10

# frontend (from frontend/)
npm install && npm run dev
npm run generate:api                           # regenerate the typed client
npm run typecheck && npm test && npm run build
npm run test:e2e                               # MOSAIQUE_CHROMIUM_PATH overrides the browser
```

**Three things that will cost you a session if you skip them:**

1. **Regenerate `frontend/openapi.json`** whenever a route or schema changes. A
   stale document means the generated client silently disagrees with the server,
   and no CI job will catch it (L-18).
2. **Never run two pytest sessions against `mosaique_test` at once.** The
   `engine` fixture drops tables and `tenants` truncates, so a concurrent run
   produces failures that look like real bugs and are not.
3. **Extract the host token with `awk '/^host_token:/{print $2}'`, not
   `| tail -1`** (L-36) — `tail -1` returns the labelled line and every request
   made with it 401s.

---

## 11. Environment and setup

- **Python 3.12+, Node 22+, PostgreSQL 16, `uv`.** `uv`, never `pip`, including
  in Dockerfiles. This is non-negotiable.
- **Configuration:** every setting is `MOSAIQUE_`-prefixed, typed and validated
  once in `config/settings.py`; extra keys are **rejected**, not ignored; and
  **nothing in the codebase reads `os.environ` directly**. `backend/.env.example`
  is the starting point. Required: `MOSAIQUE_DATABASE_URL` (must use the
  `postgresql+asyncpg` scheme — validated) and `MOSAIQUE_TOKEN_SECRET` (≥ 32
  chars).
- **Optional extras, deliberately not default dependencies:** `.[mlx]`
  (macOS/arm64 only, platform-gated), `.[moshi-server]`, `.[openai]`. The
  default install pulls in **no** model library, and a test enforces that.
- **`docker compose up`** starts PostgreSQL, the app-server and the frontend.
  On macOS the MLX runtime must run as a **native host process** — Docker cannot
  reach Metal.
- **Fail-fast configuration:** `asr_runtime=moshi_server` without a URL, or
  `llm_provider=openai` without a key, refuses to start. That is intentional —
  discovering it mid-meeting costs a real meeting its outputs.
- **In a fresh container** PostgreSQL is installed but not running:
  `pg_ctlcluster 16 main start`. See `PROJECT_STATE.md` §12 for the full
  cold-start recipe.
- **`frontend/node_modules/` is tracked in git** (L-17, 4191 files) — an
  `npm install` dirties the tree. Untracking it was judged riskier than living
  with it. Do not "fix" this incidentally.

---

## 12. Architectural decisions and ADR references

**ADR files written: 1 of 12.** Only `docs/ADR-013-mlx-development-runtime.md`
exists as a file; the rest live as rows in `PROJECT_STATE.md` §2 and in tech
spec §16.1. Writing them is scheduled for Slice 7.

| ID | Decision |
|---|---|
| **ADR-01** | WebSocket + raw PCM. No LiveKit, no SFU. |
| **ADR-02** | Python/FastAPI backend, React/TypeScript frontend. |
| **ADR-03** | Kyutai STT-1B behind `StreamingRecognizer`, separate process. |
| **ADR-04** | PostgreSQL for all durable state, **including the job queue**. |
| **ADR-05** | **Only final segments are persisted.** |
| **ADR-06** | Raw per-participant audio is stored (retention still open — Q3). |
| **ADR-07** | Intelligence is async, derived, versioned, evidence-linked. |
| **ADR-08** | `organization_id` from migration 1. |
| **ADR-09** | Single app-server process, four separable runtimes. |
| **ADR-11** | Meeting timeline derived from frame counts; client clocks never trusted for ordering. |
| **ADR-12** | Media-plane options deferred. **Non-normative — governs nothing.** |
| **ADR-13** | Model fixed; runtime is a config axis (`fake`/`mlx`/`moshi_server`). MLX develops, `moshi-server` deploys. Splits Spike B into B1 (MLX) and B2 (CUDA). |
| **D-01** | Prototype ingress is browser capture over WebSocket. |
| **D-04** | Minimal `MeetingIngress` seam — one Protocol, one enum column. |
| **D-05** | Flush trick adopted — **answered negatively for MLX** (A-12). |
| **D-03** | "Verified" requires named test evidence. |

---

## 13. Assumptions that must NOT be silently changed

Changing any of these without saying so will produce a system that looks correct
and is not.

1. **Stream time is not wall time.** Silence and segment boundaries are judged
   in stream time derived from frame counts. This bug has been introduced twice.
2. **Only final segments are persisted** (ADR-05). Interim text is disposable.
   Process memory is never the authoritative record.
3. **Raw ASR text and word timings are never overwritten.** Corrections are
   additive, always. Destroying the raw text makes L-28, the WER and every
   `[measure]` row unfalsifiable.
4. **One fact, one definition.** "What this segment says" lives once, in
   `transcript/corrections.py`. Three readers depend on it. A second copy means
   a correction visible on screen and absent from the summary.
5. **Values marked `[measure]` are guesses.** Do **not** tune them against the
   fake recognizer. They were tuned against real French audio in Slice 4.
6. **Providers fail fast; they never silently fall back to a fake.**
7. **A capability is declared, not discovered.** No `getattr(x, "cap", default)`
   for `emits_end_of_turn` or `readiness()` — the tempting default is the
   dangerous one (L-25).
8. **Anything mutated across an `await` needs a lock.** Per-participant tasks
   share runtime state (A-15).
9. **The segmenter is pure and clockless.** It takes time as an argument,
   performs no I/O, holds no socket or session. That is what lets it be tuned
   and replayed.
10. **`Meeting.asr_version` must encode runtime and quantization**, not just the
    model (ADR-13 consequence 3) — otherwise MLX-era and CUDA-era transcripts
    become indistinguishable after the fact.
11. **Search is deliberately not `ILIKE`** (L-33). `ILIKE` is accent-sensitive
    and this is a French-first product; matching is accent-insensitive, in
    Python, meeting-scoped.

`CLAUDE.md` also lists three decisions that **must not be re-litigated
unprompted**: L-28 (deferred by the maintainer), Q2's EU-residency half (a
product/legal call, not an engineering one), and L-33.

---

## 14. Known issues and deferred debt

**Open defects**

- **L-28 — the orphaned sentence-final word, 8 of 30 segments (27%).**
  **DEFERRED BY DECISION**, not by oversight. The silence tick closes segments
  where the audio has only a 160–560 ms gap, orphaning each sentence's last
  word — and WER scored 1.43% straight through it, which is the lesson: **judge
  segmentation by looking at boundaries, never by a word-level score.** The
  suspected cause (emission lag outrunning `transcribed_offset_ms`) is
  **inferred, not observed** — do not encode it anywhere as fact. Pinned by
  `tests/unit/test_l28_orphaned_final_word.py`, a characterization test that
  asserts behaviour that is *wrong*, on purpose. **Do not reopen unprompted.**
- **L-38** — paragraph grouping *hides* L-28's orphans; it does not fix them.
- **L-29** — the `capture → gateway_recv` latency hop is meaningless (p95 reads
  ≈ 3.2×10⁹ ms). The browser stamps `Date.now()` and the server subtracts
  `time.monotonic()`; the two have no common origin. A broken metric, not a
  broken pipeline. Every other hop is sound because both its ends are
  server-side.
- **L-18** — **no CI exists.** No `.github/` directory. Every check is manual.
- **L-24** — the sentence-end rule will split a French abbreviation (`M.`,
  `etc.`). Not yet observed in a real fixture.
- **L-21** — reconnect grace and idle close are both 30 s and can race.
- **L-16** — a guest cannot read the transcript once the meeting ends.
- **L-37** — `PARAGRAPH_SILENCE_MS` is a guess, and it decides how the
  transcript reads.
- **L-39 / L-40** — no correction history (a second edit overwrites the first);
  timestamps are not correctable, because FR-11's seek arithmetic derives from
  them.
- **The join path is deliberately unfixed.** Degraded-state UX blocks meeting
  *creation* when the ASR runtime is down. `JoinPage` has the same shape — a
  participant can still join a meeting whose transcription engine is down and
  speak into nothing. That is a product call, not a wiring one. **Do not fix it
  without asking.**

**Intentionally deferred features**

No transcript editing history · no billing or usage accounting · no
multi-language (French-first; Darija is roadmap) · no external conferencing
platform integration (every participant must run Mosaïque — L-1) · no horizontal
scale (single host — L-3) · magic-link auth and guest links (Slice 7 — host
tokens are pasted by hand today, L-11) · rate limits · `DELETE /meetings/{id}`
and the retention job (Q3 — **nothing deletes anything yet**) · indexed search ·
prompt-injection defence beyond Level 1 · the eleven unwritten ADR files.

---

## 15. Risks for the next multi-user / cloud phase

Ranked by how much they would cost if discovered late.

1. **A-3 is unanswered: nobody has run two concurrent streams through a real
   serving runtime.** Concurrency is a property of the serving runtime, not the
   model, so no amount of MLX work touches it. Everything about four
   participants rests on this.
2. **A-8 is unanswered: every run so far is loopback on one machine.** The
   12.5 frames/s per participant rate has never met a real network — no jitter,
   no loss, no NAT, no TLS termination, no variable RTT. `tools/replay --base-url`
   against a second machine is the harness for it and has never been used.
3. **A-16: every number in §8 was measured on MLX and does not describe CUDA.**
   First-word latency, WER, realised speed, segment-close latency — all of it
   must be re-measured on the production runtime before it can be quoted.
4. **`moshi_server.py` has never met a real server.** The translation, reconnect
   and health arithmetic are tested against a fake transport. The first real
   connection will find something; budget for it rather than treating the
   backend as done.
5. **Segmentation thresholds were tuned on one speaker, one 64 s recording.**
   The speaker's largest mid-phrase gap (1 120 ms) and shortest real sentence
   break (880 ms) **overlap**, so no silence threshold separates them. A second
   voice can move every threshold. On `moshi-server` the VAD signal exists and
   §9.3's primary rule becomes live — which means segmentation behaviour will
   *change* when you switch runtimes, and that is expected, not a regression.
6. **Cross-talk attribution is completely unmeasured** (Spike A, A-1, L-2).
   Today's attribution is endpoint capture: each microphone is one speaker.
   Two people in one room with a speakerphone is a different problem and nobody
   has measured it.
7. **Security and tenancy are Level 1.** Host tokens are pasted by hand, there
   are no rate limits, prompt-injection defence is minimal, and the §13.5
   checklist is unstarted. Multi-user over a network is where this stops being
   theoretical.
8. **Data residency (Q2's open half) is unanswered.** OpenAI is a US processor
   and this is a French-SMB product handling meeting audio. `llm_base_url` makes
   an EU-resident endpoint a config change — that is mitigation, not an answer.
   A-11 ("joining is consent") is the same conversation and needs counsel, not
   engineering.
9. **No CI (L-18)** means every claim in this document was verified by hand and
   can silently rot. Two machines producing the same test count is the only
   cross-check that exists.
10. **Nothing deletes anything** (Q3). Raw per-participant audio is stored and
    now *served*. Retention is still a Slice 7 job.

---

## Recommended Next Milestone

**Two remote participants can join one real meeting, each participant has an
independent audio stream, both streams are transcribed in real time by a
remotely hosted production-style Kyutai ASR runtime, the UI displays
speaker-attributed transcription, and ending the meeting produces the finalized
transcript, summary, decisions, and action items.**

This milestone is deliberately the **union of Slice 6B and the two-participant
half of Slice 6C**, because the two halves cannot honestly be separated: MLX
refuses a second concurrent session in code (L-26), so "two participants on a
real model" *is* "a remotely hosted serving runtime". It is also the first
milestone that exercises A-8 — two remote participants means a real network, not
loopback.

**Do not implement it from this document.** What follows is orientation for
whoever scopes it, not a plan.

**What already exists and should not be rebuilt:** the two-participant path is
built and tested on fakes (Slice 2), the `moshi_server` backend exists behind
`KyutaiBackend` with its protocol translation tested, `tools/replay` can drive
N streams over real WebSockets against a remote `--base-url`, and the whole
end-of-meeting intelligence chain works. The milestone is mostly about running
existing code against real infrastructure and measuring what happens.

**What this milestone must prove, and what would count as proof:**

- `MOSAIQUE_ASR_RUNTIME=moshi_server` plus a URL is **the entire change**.
  If any code in the meeting, transcript or realtime layers has to move, the
  ADR-13 seam is broken — that is the single most important finding this
  milestone can produce, and it should be reported as such rather than patched
  around.
- Two independent streams are transcribed concurrently without cache
  interleaving or cross-attribution (**A-3**, the thing MLX cannot do).
- Real network conditions between participants and server (**A-8**) — the first
  non-loopback run this project will ever have.
- Speaker attribution holds across two remote browsers, end to end.
- Ending the meeting still produces transcript, summary, decisions and actions
  with valid evidence links.

**Expect these to need attention** (each is a known unknown, not a prediction of
failure): segmentation behaviour will *change* on `moshi-server` because
`EndOfTurnEvent` becomes live and §9.3's primary rule stops being dead code;
`end_of_turn_threshold` becomes measurable for the first time and its 0.5 guess
should be measured, not assumed; `Marker`-based flush (D-05) may finally be
worth what MLX could not deliver; and every §8 number will need re-measuring
against the new runtime with the runtime named beside it (A-16, ADR-13
consequence 3).

**Before proposing infrastructure for this milestone**, read
`docs/IMPLEMENTATION_PLAN.md` §"Slice 6B" and §"Slice 6C" — they already carry
exit gates for exactly this work, including the measurement list — plus
`docs/ADR-013-mlx-development-runtime.md` and `PROJECT_STATE.md` §7 (the
assumption register) and §8 (the measured-values ledger). Then look at the code.
**This handoff document is a map, not the territory; the repository is
authoritative and some of what is written here will have aged by the time you
read it.**
