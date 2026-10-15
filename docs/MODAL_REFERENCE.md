# Modal + vLLM reference: lessons from `voxtral-ar-realtime`

**Source:** `github.com/Aymenec-212/voxtral-ar-realtime`, branch `main` at commit `3dd4f96` (14 Oct 2026).

**How this was produced:** a read-only inspection on 15 Oct 2026.
- Nothing was modified, deployed or called on a cloud service.
- No `.env` file, key file or audio file was opened. None is tracked in git.

**Evidence labels used throughout:**
- **[code]** seen in the code.
- **[test]** covered by the CPU test suite. All 65 tests and the ruff checks were re-run and pass at `3dd4f96`.
- **[gpu-log]** seen in Modal logs the maintainer captured on 11 and 14 Oct 2026. These logs are not in the repo.
- **[doc]** stated only in the README or code comments.
- **[unverified]** nobody has measured it.

Line numbers refer to `3dd4f96`.

---

## 0. The short version

- **What it is:** `mistralai/Voxtral-Mini-4B-Realtime-Arabic` at a pinned revision, served by **vLLM v0.31.0** through its **`/v1/realtime` WebSocket**. It ran on **one NVIDIA L4 on Modal**, behind a FastAPI gateway that is the only public surface. vLLM listens on `127.0.0.1` only.
- **Not exercised on a GPU:**
  - more than one stream at a time, so batching is unmeasured;
  - sessions longer than a few minutes;
  - reconnects;
  - `modal deploy`. Only `modal serve` runs are documented.
- **For Mosaïque:** the deployment plumbing transfers almost as is: Dockerfile, weights on a Volume, engine supervision, fail-fast startup and the vLLM protocol client. The session model does not transfer: it is one utterance per WebSocket, capped at 5 minutes. Per-participant, meeting-length streams need a new design.
- **The biggest open risk for meetings:** the model writes 1 token per 80 ms, so about 45,000 tokens per participant-hour. At the deployed `--max-model-len 16384`, a single session tops out at about 21.8 minutes. On an L4 the whole KV cache holds about 36 participant-minutes if it grows linearly (§6.3).

---

## 1. Model, runtime and serving protocol

| Item | Value | Where | Evidence |
|---|---|---|---|
| Model | `mistralai/Voxtral-Mini-4B-Realtime-Arabic`, a Voxtral **Realtime** model, not Voxtral Mini or Small (chat or transcribe) | `voxtral_rt/config.py:10` | [code] |
| Revision pin | `a8b0156f0dd61e2fcfe73e16dbbee600c4a967f1` (public Hugging Face commit) | `voxtral_rt/config.py:11-12` | [code] |
| vLLM architecture | `VoxtralRealtimeGeneration`, Mistral-format weights, `bfloat16` | — | [gpu-log] |
| Runtime | vLLM **v0.31.0**, from base image `vllm/vllm-openai:v0.31.0` | `docker/Dockerfile:1-4` | [code] [gpu-log] |
| Launch | `vllm serve <dir> --host 127.0.0.1 --port 8001 --served-model-name <id> --tokenizer-mode mistral --max-model-len 16384 [VLLM_EXTRA_ARGS]` | `voxtral_rt/engine.py:40-65` | [code] [test] |
| Engine protocol | vLLM `/v1/realtime` WebSocket, JSON text frames, base64 PCM16 | `voxtral_rt/upstream.py:1-8, 106-117` | [code] [gpu-log] |
| Public protocol | Our own `WS /v1/transcribe`: binary PCM16 in, JSON events out | `voxtral_rt/gateway.py:1-17, 113-126` | [code] [test] |
| Tasks vLLM exposed | `generate`, `transcription`, `realtime`; route `/v1/realtime` → `realtime_endpoint` | — | [gpu-log] |

**Model timing:**
- One token per 80 ms of audio, so 12.5 tokens/s (`voxtral_rt/metrics.py:13-17`).
- A built-in transcription delay of 480 ms, which is 6 frames (`metrics.py:18-20`).

Measured live at 12.4 to 12.5 tokens/s, with lag of about 0.5 s [gpu-log, maintainer report].

---

## 2. Modal deployment map

All in `deploy/modal_app.py` unless noted. Modal is pinned to `modal==1.6.1` (`pyproject.toml:27-28`).

| Concern | Config | Lines |
|---|---|---|
| App, Volume, image | `modal.App("voxtral-ar-realtime")`; `Volume.from_name("voxtral-models", create_if_missing=True)`; `Image.from_dockerfile(docker/Dockerfile).entrypoint([])`. Modal builds the image on its own builders. | 30-34 |
| Container env | Only `MODELS_DIR` and `PORT`. `API_KEY` comes from the Secret. | 36-41 |
| Weight caching | `download_weights`: a **CPU-only** Modal function (`cpu=2, memory=4096`, 60 min timeout) runs `ensure_weights` into the Volume, then `volume.commit()`. | 44-66 |
| Weight logic | `snapshot_download(repo, revision, ignore=["assets/*", "model.safetensors"])` plus a `.complete` marker file holding the revision. A new revision downloads again. | `voxtral_rt/weights.py:12-37` [test] |
| GPU server | `@app.server(gpu="L4", port=8000, volumes={/models}, secrets=[Secret.from_name("voxtral-api-key", required_keys=["API_KEY"])])` | 69-85 |
| Scaling | `max_containers=1` (hard cost cap); `scaledown_window=5 min`; `target_concurrency=16` | 78-83 |
| Startup | `startup_timeout=20 min`. This is longer than the launcher's own `ENGINE_READY_TIMEOUT_S=900`, so the launcher's error is what you see. | 80-82; `config.py:27,48` |
| Lifecycle | `@modal.enter`: `require_api_key`, then `Popen(["python3","-m","voxtral_rt"])`, then `wait_until_listening(8000)`. `@modal.exit`: terminate, wait 60 s, kill. | 86-100 |
| Fail fast | `wait_until_listening` polls TCP :8000 every 1 s and **raises as soon as the launcher exits**, instead of idling a paid GPU until `startup_timeout` | 113-127 [test] |
| Auth gate | `unauthenticated=True`: Modal's proxy auth is off, and the gateway's key is the only gate | 84 |
| In-container launcher | weights check → `Engine.start()` → poll vLLM `/health` every 1 s → only then `uvicorn` on `0.0.0.0:8000` | `voxtral_rt/__main__.py:47-62`; `engine.py:67-88` [test] |
| Process chain | Modal runtime → launcher and gateway (pid 4) → vLLM API server (pid 5) → vLLM EngineCore (pid 38, over ZMQ) | [gpu-log] |

**Image specifics** (`docker/Dockerfile`):
- **Lines 6-7:** `ENTRYPOINT []` and `HF_XET_HIGH_PERFORMANCE=1`.
- **Lines 8-16:** install vLLM's missing **audio extras** (`av scipy soundfile soxr mistral_common[audio]`) under a constraint freeze of the base image's pins, plus a build-time import check.
- **Line 22:** a `python` symlink.
- **Line 25:** the gateway is installed with `--no-deps`.

---

## 3. How clients connect, and what the events look like

**Observed in code and tests:**
- **Transport:** a WebSocket at `/v1/transcribe` with **one utterance per connection** (`gateway.py:3-9, 113-126`). HTTP routes:
  - `GET /` and `/static`: the demo page;
  - `GET /health`: 200 or 503 depending on vLLM `/health` (`gateway.py:93-96`);
  - `GET /v1/metrics/stream`: Server-Sent Events, one JSON snapshot per second (`gateway.py:98-111`).
- **Client → server:**
  - binary frames of **raw PCM16 little-endian, mono, 16 kHz**, any chunk size;
  - then the text frame `{"type":"stop"}` (`gateway.py:202-225`).
  - Empty frames and unknown text frames give `bad_request` and close 1003.
- **Server → client:**
  - `{"type":"ready"}`, sent only after the vLLM handshake (`gateway.py:153-154`);
  - `{"type":"delta","text"}` for **every** vLLM delta, empty ones included, so the rate is about 12.5/s (`gateway.py:228-236`);
  - `{"type":"metrics",...}` every 1 s (`gateway.py:239-242`);
  - `{"type":"final","text","metrics"}`, then close 1000.
- **Errors:** `{"type":"error","code","message"}`, then a close:
  - `busy` (1013): the per-container `SessionGate` is full (`gateway.py:55-75, 122-124`);
  - `bad_request` (1003);
  - `upstream_error` (1011);
  - `time_limit`: a final first, then close 1000 (`gateway.py:156-169, 176-199`).
- **Gateway ↔ vLLM** (`upstream.py`), in order:
  1. wait for `session.created`;
  2. send `session.update {model}`;
  3. send a non-final `input_audio_buffer.commit`, which **starts generation**;
  4. send `input_audio_buffer.append {audio: base64}`;
  5. receive `transcription.delta {delta}`;
  6. send `input_audio_buffer.commit {final:true}`;
  7. receive `transcription.done {text, usage}`.

  `finish()` is idempotent. A vLLM `error` event, a closed socket or a non-JSON frame raises `UpstreamError` (`upstream.py:67-117`) [test with `tests/fake_vllm.py`].
- **Partial vs final:** deltas are **append-only text**. No revisions, timestamps or segment boundaries were observed. The final carries the full text and token usage.
- **Audio in the browser:** `getUserMedia` (mono, with echo cancellation, noise suppression and auto gain on), then an AudioWorklet:
  - mix to mono;
  - linear resample from the native rate to 16 kHz;
  - convert to Int16;
  - send 100 ms frames of 1,600 samples, 3,200 B each (`web/pcm-worklet.js:4-55`; `web/mic.js:87-105`).
- **Audio from a file:** `clients/stream_wav.py:25-45` requires a 16 kHz mono 16-bit WAV and sends paced chunks (default 100 ms).
- **Auth:** when `API_KEY` is set, `/v1/transcribe` and `/v1/metrics/stream` require `?token=`.
  - The token is compared in constant time (`gateway.py:129-136`).
  - A bad or missing token closes the WebSocket with 1008, or returns 401 on the stream.
  - `/` and `/health` stay public.
  - uvicorn log lines are redacted to `token=***` (`__main__.py:15-40`). Tested against real uvicorn output (`tests/test_main.py:85-108`).

**Documented intent, beyond the code:**
- The README describes the same protocol.
- "Any chunk size" is accepted by the gateway [code], but only 100 ms chunks were exercised on a GPU.

---

## 4. Credentials, and risks for production reuse

**Where credentials come from** (no values shown):
- **`API_KEY`:** a Modal Secret named `voxtral-api-key` (`modal_app.py:25-28, 76`), injected as an environment variable.
  - Checked non-empty at container start (`modal_app.py:90, 103-110`).
  - Read once into `Settings.api_key` (`config.py:45`).
  - Clients send it as a query parameter (`web/mic.js:34-38`; `clients/stream_wav.py:86-90`).
- **Modal account credentials:** on the developer's machine via `modal setup`. Never in the repo.
- **Hugging Face:** no token is referenced; the model is public. `huggingface_hub` would pick up an ambient HF token if one were added to the container env, and none is (`modal_app.py:38-41`).
- **Repo:** no `.env`, key or token files are tracked (checked with `git ls-files`).

**Risks if reused as is:**
1. **Auth:** one static, shared key. There is no per-tenant identity, no rate limiting beyond the per-container session gate, and changing the key needs a container restart, because the secret is read at start.
2. **Key in the URL:** it is redacted only in uvicorn's logs. The Modal edge, proxies and browser tooling may record query strings [unverified]. For server-to-server clients such as a Pipecat backend, use a header.
3. **No platform auth:** with `unauthenticated=True`, the gateway is the only gate.
4. **No redundancy:** `max_containers=1` is a single point of failure. There is no reconnect or resume, and a container restart drops live sessions.
5. **Weak observability:** metrics are in memory only, and there is no transcript persistence or audit trail.
6. **Data residency:** the dev deployment ran in Modal's `us-east`. Meeting audio from EU or Moroccan customers would cross borders.
7. **Reproducibility:**
   - the base image is pinned by tag, not by digest;
   - audio extras resolve fresh on each rebuild, constrained only by the base image's pins;
   - the revision pin can disappear from the Hub. The README documents the `RevisionNotFoundError` fix.
8. **Frame size:** no limit on the size of one audio message beyond uvicorn's defaults [code].

---

## 5. Evidence: what is proven and what isn't

**Proven:**
- **[test]** 65/65 tests plus ruff pass on CPU. They cover:
  - protocol order and error mapping (`tests/test_upstream.py`, `tests/test_gateway.py`);
  - auth, 1008 and 401 (`test_gateway.py:67-115`);
  - log redaction against real uvicorn output (`test_main.py:85-108`);
  - fail-fast startup and the key requirement (`tests/test_modal_app.py`);
  - weight caching (`tests/test_weights.py`);
  - metrics (`tests/test_metrics.py`);
  - the rule that only `upstream.py` may use vLLM's event names (`tests/test_boundaries.py`).
- **[gpu-log, 11 Oct]** A full L4 boot with weights already on the Volume. Launch to ready took **about 4 min 45 s**:

  | Phase | Time |
  |---|---|
  | vLLM start (imports, config, engine process) | ~118 s |
  | Model load (weight read 6.26 s) | 26 s |
  | `torch.compile` (reported 84.07 s) | ~89 s |
  | Profiling, KV cache, 2 CUDA-graph captures | ~50 s |
  | Health check passes, port 8000 opens | 2 s |

  Memory on the L4:
  - 22.06 GiB visible;
  - vLLM budget 92 %, 20.3 GiB;
  - weights 8.43 GiB;
  - peak activations 2.09 GiB;
  - CUDA graphs 0.37 GiB;
  - **KV cache 9.45 GiB = 27,082 tokens**.

  vLLM logged "max concurrency 1.65× at 16,384 tokens/request".
- **[gpu-log / maintainer report, 11-14 Oct]**
  - Live browser sessions ran end to end through Modal's edge, so `@app.server` does proxy WebSockets.
  - Lag was about 0.5 s and throughput 12.4-12.5 tokens/s.
  - One session grew KV use from 1.0 % to 3.3 % in about a minute. Linear math predicts 2.8 %/min.
- **[gpu-log, 14 Oct]** After the auth change, connection lines show `token=***` and the key is absent from the captured log.
- **[gpu-log, 11 Oct]** The first boot died with `soundfile is not installed`, which is why Dockerfile lines 8-16 exist. Under the old `Server.start()`, Modal printed "Ready for task" *before* the engine had booted, which is why `wait_until_listening` exists.

**Not verified:**
- **Concurrency:** more than one concurrent stream on a GPU, batching behaviour, or the real session ceiling. `MAX_SESSIONS=4` is a **memory estimate**, not a measurement.
- **Long or edge sessions:** sessions past about 5 minutes; the `time_limit` path on a GPU; what vLLM does when a session reaches `--max-model-len`.
- **Recovery and lifecycle:** reconnect or resume (none implemented); `modal deploy` (only `modal serve` was run); the 401 check on a GPU (the curl run had an unset URL; tests cover it).
- **Cold starts:** only one detailed boot was timed. Persisting the compile cache, memory snapshots and `--enforce-eager` were not tried.
- **Cost:** under load, and per audio hour. The figures of about $0.20 at 4 streams and about $0.11 at 7 are **arithmetic** from $0.80 per GPU-hour.
- **Accuracy:** WER and CER were not measured by this project.
- **Elsewhere:** Docker outside Modal; GitHub CI results (not checked from this environment).
- **Dev-mode fragility:** a short DNS outage on the developer's laptop produced `AppHeartbeat` errors in `modal serve` and one degraded session (15 s to first text). A restart fixed it. Run anything long-lived with `modal deploy`, not `modal serve`.

---

## 6. For the Mosaïque Builder: reuse, adapt or reject

### 6.1 Reuse, nearly as is

| What | Where | Why |
|---|---|---|
| Audio-extras install with constraint freeze and build-time import check | `docker/Dockerfile:8-16` | Without it, vLLM dies on a **billed GPU** during its profiling run |
| CPU `download_weights` into a Volume, with a marker file | `deploy/modal_app.py:44-66`, `voxtral_rt/weights.py` | No GPU time is spent downloading; weights read in about 6 s at boot |
| `Engine`: subprocess, health polling, fail-fast, timeout, SIGTERM then SIGKILL | `voxtral_rt/engine.py:24-109` | Small interface; tested |
| `wait_until_listening` in `@modal.enter` | `deploy/modal_app.py:113-127` | Stops a dead boot within 1 s instead of idling the GPU until `startup_timeout` |
| `UpstreamSession`, the vLLM realtime client | `voxtral_rt/upstream.py` | The verified handshake order, base64 audio, idempotent finish and error mapping. A good core for a Pipecat STT service |
| `tests/fake_vllm.py` and the boundary test | `tests/fake_vllm.py`, `tests/test_boundaries.py` | Whole-system CPU tests with error and drop switches; keeps vLLM's protocol in one module |
| Log redaction filter and its test | `voxtral_rt/__main__.py:15-40`, `tests/test_main.py:85-108` | Any credential in a URL leaks through uvicorn otherwise |
| Metric definitions and Prometheus names | `voxtral_rt/metrics.py:13-30, 35-122, 174-224` | `lag_ms` (about 480 ms means keeping up), `first_text_ms`, `tokens_per_s` (12.5 means real time), and KV usage from vLLM `/metrics` |
| vLLM on loopback, one public gateway | `engine.py:46-50` | Security and a stable contract |

### 6.2 Adapt

- **Session model:**
  - **Old:** one utterance per WebSocket, `stop` → final, 300 s cap (`config.py:26`).
  - **New:** one long-lived vLLM session **per participant track**, with planned rotation before the context limit, interim results from deltas, and finals at rotation or endpointing.
- **Capacity gate:** `SessionGate` (`gateway.py:55-75`) is per container and sized from 5-minute sessions. Recompute it from the KV math in §6.3, measure compute limits, and make it meeting-aware: admit a meeting only if all its participants fit.
- **Auth:** keep `?token=` only for browsers. For server-to-server, such as Pipecat to the STT service, use headers and per-tenant or short-lived credentials.
- **Scaling:**
  - **Old:** `max_containers=1`.
  - **New:** more than one container, with routing that keeps a meeting's sessions on one container (each WebSocket already stays on its container).
  - For scheduled meetings, warm up ahead of time with `min_containers` or a warm-up call, because a cold start takes about 5 minutes.
- **Model config:** set `MODEL_ID` and `MODEL_REVISION` (`config.py:10-12, 39-40`) and the fake's `DEFAULT_MODEL` (`tests/fake_vllm.py:24`) to the 2602 model.
- **Engine flags:** `VLLM_EXTRA_ARGS` (`engine.py:63-64`) is the hook for `--max-model-len` and compilation settings.
- **Modal API:** `@app.server` with `modal==1.6.1` is verified. Re-check it if you upgrade Modal.

### 6.3 Compatibility notes

**`mistralai/Voxtral-Mini-4B-Realtime-2602`** (Hugging Face page, read 15 Oct 2026):
- **Family:** the Arabic model is fine-tuned from 2602, so the same vLLM path should apply. Not run here [unverified].
- **Size and languages:** about 4B parameters (a ≈3.4B language model plus a ≈970M causal audio encoder, both with sliding-window attention). 13 languages, including Arabic, French and English.
- **Files:** `consolidated.safetensors` (8.86 GB), `model.safetensors` (8.86 GB), `params.json`, `tekken.json`, `config.json`, and no `assets/`. So `IGNORE_PATTERNS` in `weights.py:18` stays valid and halves the download. The repo head at inspection was `2769294da9567371363522aac9bbcfdd19447add`; pin it and re-verify.
- **Delay:** set by `"transcription_delay_ms"` in `tekken.json`. Allowed values are multiples of 80 ms up to 1200, or 2400; 480 is the default. **No per-session parameter is documented**, so the delay is per deployment, and changing it means editing the file on the Volume.
- **Model card's serve recipe:**
  - It uses `--compilation_config '{"cudagraph_mode": "PIECEWISE"}'` and `VLLM_DISABLE_COMPILE_CACHE=1`, and points at nightly vLLM. This repo uses neither, on vLLM 0.31.0 [unverified which is better].
  - It does not mention `--tokenizer-mode mistral`. This repo passes it, and it works for the Arabic model.
  - The default `--max-model-len` is 131,072. One hour of audio needs at least 45,000.

**vLLM `/v1/realtime`:**
- Only the event set in `upstream.py:1-8` has been exercised.
- vLLM's realtime events are its own. Don't assume an OpenAI-Realtime client or a Pipecat OpenAI-Realtime service speaks it; verify against vLLM's source before reusing one.

**Per-participant sessions, capacity on one L4 at `--max-model-len 16384`:**
- A participant consumes **750 tokens per minute**, so one session is capped at about **21.8 min** (16,384 × 0.08 s).
- The KV cache (27,082 tokens) holds about **36 participant-minutes** in total if KV grows linearly. That holds unless vLLM frees KV outside the sliding window for this model, which is unverified: only the first minute was observed.
- **Examples:**
  - rotating every 5 min gives ≤ 7 concurrent participants by memory;
  - 4 participants can each run about 9 min before the cache fills.
- The compute ceiling is unmeasured.

**Pipecat** (not inspected in this repo):
- Write a custom STT service per participant that wraps `UpstreamSession`, or calls the gateway with header auth.
- Map deltas to interim transcripts and the rotation or stop final to a final transcript.
- Resample each track to 16 kHz mono PCM16 before sending.
- The model doesn't diarize. Speaker attribution has to come from separate per-participant tracks.

### 6.4 Reject for Mosaïque

- **Browser demo page and AudioWorklet** (`voxtral_rt/web/*`), unless Mosaïque captures audio in the browser. Pipecat transports would supply the audio.
- **The one-utterance protocol and the 5-minute cap** as the product protocol.
- **One shared static key with platform auth off** as production auth.
- **In-memory metrics as the only observability.** Export Prometheus or OpenTelemetry instead.

---

## 7. Questions the new design must answer

1. **Multiple segments per session:** can one vLLM realtime connection carry several segments (repeated non-final commits), and what happens after `transcription.done`? This decides the rotation strategy.
2. **Reaching `--max-model-len`:** what does vLLM 0.31 do when a realtime session hits it? An error event, a silent stop, or a close? Does its hybrid KV manager reclaim memory outside the sliding window for this model, so per-session KV is bounded?
3. **Concurrency:** how many **continuous** participant streams does one GPU sustain with steady `lag_ms` and `tokens_per_s` near 12.5? Which GPU (L4, L40S, A100) has the best cost per participant-hour? This needs a load test.
4. **Rotation:** how do we rotate sessions without losing words at the boundary? Options are overlapping sessions, cutting at silence detected by VAD, or accepting about 0.5 s of re-warm.
5. **Timestamps:** does vLLM realtime emit any word or segment timestamps for Voxtral? None were observed. If not, how do we align participants? Options include gateway wall-clock time with the 480 ms offset, or a batch pass after the meeting.
6. **Endpointing:** what defines a "final" in a meeting? VAD, punctuation, a time window, or model behaviour?
7. **Delay:** which `transcription_delay_ms` fits meetings? Higher means more accurate but later, and it is a deployment-wide setting.
8. **Data residency:** which Modal region, and what data-residency obligations apply for meeting audio (GDPR, Morocco's loi 09-08)? Is transcript or audio retention allowed?
9. **Compilation:** keep `torch.compile` with a persisted cache, use the model card's `PIECEWISE` recipe, or use `--enforce-eager` to cut cold starts? Measure each.
10. **Warm-up:** what pre-warm policy (`min_containers`, a scheduled warm-up) fits scheduled meetings, given about 5 minutes of cold start against $0.80/h idle cost on an L4?
11. **Pipecat transport:** which transport, which per-track sample rate, and where does resampling to 16 kHz happen?
12. **Auth model:** per-tenant keys or short-lived tokens, and how they rotate without restarting containers.
