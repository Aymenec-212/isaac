# Mosaïque

Realtime meeting intelligence, French-first.

**Status: Slice 2 — two participants and the replay harness, on fakes.** Two
people can join the same meeting from their own browsers and watch one merged
transcript, each line under whoever said it, with a participant panel showing
who is in the room and who is talking. Ending the meeting produces a summary
with decisions and actions that cite real transcript segments. Every model in
that path is a fake: `FakeRecognizer` and `FakeLLMProvider`. Real Kyutai
arrives in Slice 4, a real provider in Slice 5.

Not in this slice: reconnect handling, overload behaviour, `stream.status`,
four participants, audio scrubbing, search, magic-link login.

`PROJECT_STATE.md` is the only document that describes what actually exists.
The Technical Specification is normative for what is being built.

---

## Bootstrap from nothing

Prerequisites: Python 3.12+, Node 22+, PostgreSQL 16 (or Docker), and
[uv](https://docs.astral.sh/uv/). This project uses **uv**, not pip.

```bash
# 1. uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone or initialise
git clone <remote> mosaique && cd mosaique
# ...or, starting fresh:
#   mkdir mosaique && cd mosaique && git init -b main

# 3. Backend environment
cd backend
uv venv                       # creates .venv on Python 3.12
uv pip install -e ".[dev]"
cp .env.example .env          # then set MOSAIQUE_TOKEN_SECRET

# 4. Database
createdb mosaique             # or: docker compose up -d postgres
uv run alembic upgrade head   # migration 1: all eight tables
uv run python -m mosaique.app.seed   # prints a host token — copy it

# 5. Run the API
uv run uvicorn mosaique.app.main:create_app --factory --reload --port 8000

# 6. Frontend, in a second terminal
cd frontend
npm install
npm run generate:api          # regenerate the typed client from openapi.json
npm run dev                   # http://localhost:5173
```

Paste the host token from step 4 into the app when it asks. That stands in for
login until Slice 7 (blueprint R-2).

## Everything at once

```bash
docker compose up --build
# frontend  http://localhost:8080
# API       http://localhost:8000/docs
```

Migrations and seeding run from the entrypoint before the server accepts traffic.

## Daily commands

```bash
cd backend
uv run pytest -q                       # 117 tests
uv run pytest -m "not integration"     # unit only, no database needed
uv run ruff check . && uv run ruff format .
uv run mypy                            # strict
uv run alembic revision --autogenerate -m "..."
uv run python tools/export_openapi.py ../frontend/openapi.json

cd frontend
npm run typecheck && npm test && npm run build
npx playwright install chromium && npm run test:e2e   # needs a running backend
```

### The replay harness

`tools/replay` drives N participant streams into the running gateway over real
WebSockets, at a chosen speed factor, and writes a JSON report with per-segment
latency. It is the tool for debugging anything realtime: a failure you can
replay is a failure you can fix.

```bash
cd backend
# a scenario is a timing script: who speaks, from when, out of which fixture
uv run python -m tools.replay run tools/replay/scenarios/two-participants.json \
  --host-token "$(uv run python -m mosaique.app.seed | tail -1)" \
  --speed 10 --report /tmp/replay.json

# fixtures are raw 24 kHz s16le mono; synthesise one, or point at a recording
uv run python -m tools.replay make-fixture reunion.pcm --ms 20000
```

`--speed 10` replays twenty seconds of meeting in about five, and produces the
same transcript as real time: segmentation is judged in stream time derived
from frame counts (ADR-11), never against a wall clock. That equivalence is
asserted by `test_ten_times_speed_produces_the_same_transcript_as_real_time`,
and it is the property the harness lives or dies by.

Regenerating the OpenAPI document is not optional: CI fails if the committed
`frontend/openapi.json` differs from what the code produces, because a stale
document means the typed client silently disagrees with the server.

## Layout

```
backend/src/mosaique/
  config/         typed settings, fail fast
  domain/         entities, meeting state machine, error taxonomy (pure)
  app/api/        FastAPI routers
  app/auth/       tokens and the single authorization check
  persistence/    models, repositories, alembic migrations
  realtime/       gateway, protocol, sessions, ingress   (Slice 1, roster Slice 2)
  speech/         StreamingRecognizer + adapters          (Slice 1 fake, Slice 4 Kyutai)
  transcript/     segmenter                               (Slice 1)
  intelligence/   LLMProvider and output schema           (Slice 1 fake, Slice 5 real)
  jobs/           processor loop                          (Slice 1)
  observability/  structured logging, metrics
backend/tools/
  replay/         N-stream replay harness                 (Slice 2)
frontend/src/
  api/            typed client generated from OpenAPI
  meeting/        live view, participant panel            (Slice 1, panel Slice 2)
  realtime/       WS client, reconciler, roster           (Slice 1, roster Slice 2)
  review/         summary, decisions, actions             (Slice 1)
```

Empty directories are deliberate: they are the module boundaries the
specification defines, and they get filled in slice order.

## What Slices 1 and 2 prove

- Two participants in their own browsers see one merged transcript, correctly
  attributed, and the two screens agree.
- A replay at 10x produces the same transcript as one at 1x.
- The runtime learns who is in a meeting from ingress events, never from the
  transport — it cannot count sockets even if it wanted to.
- Audio captured in a browser becomes an attributed French transcript live.
- Interim text is visibly provisional; only final segments are persisted.
- `POST /end` twice yields one COMPLETED meeting and one intelligence job.
- A crash mid-finalization is recovered on startup without losing segments.
- A failed summary leaves the transcript and meeting state untouched.
- Summary decisions and actions cite segment ids that actually exist.
- Nothing downstream of the ingress imports a transport type, and nothing
  outside the Kyutai adapter imports a model library — both enforced by a test
  that parses the source, not by review.

## Running a meeting locally

```bash
# terminal 1
cd backend && uv run uvicorn mosaique.app.main:create_app --factory --reload --port 8000
# terminal 2
cd frontend && npm run dev
```

Create a meeting, click the invite link it prints, accept the consent notice,
and speak. The fake recognizer emits a scripted French conversation keyed to
how much audio it has received, so the transcript is deterministic.

For a second participant, open the same invite link in another browser profile
or a private window and join under a different name. Both windows should show
the same transcript with each line attributed to its speaker.
