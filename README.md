# Mosaïque

Realtime meeting intelligence, French-first.

**Status: Slice 1 — one participant, end to end, on fakes.** You can create a
meeting, open the invite link, accept the consent notice, grant the microphone,
watch French text appear live and firm up into final segments, end the meeting,
and read a summary with decisions and actions that cite real transcript
segments. Every model in that path is a fake: `FakeRecognizer` and
`FakeLLMProvider`. Real Kyutai arrives in Slice 4, a real provider in Slice 5.

Not in this slice: a second participant, reconnect handling, `stream.status`,
audio scrubbing, search, magic-link login.

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
uv run pytest -q                       # 113 tests
uv run pytest -m "not integration"     # unit only, no database needed
uv run ruff check . && uv run ruff format .
uv run mypy                            # strict
uv run alembic revision --autogenerate -m "..."
uv run python tools/export_openapi.py ../frontend/openapi.json

cd frontend
npm run typecheck && npm test && npm run build
npx playwright install chromium && npm run test:e2e   # needs a running backend
```

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
  realtime/       gateway, protocol, sessions, ingress   (Slice 1)
  speech/         StreamingRecognizer + adapters          (Slice 1 fake, Slice 4 Kyutai)
  transcript/     segmenter                               (Slice 1)
  intelligence/   LLMProvider and output schema           (Slice 1 fake, Slice 5 real)
  jobs/           processor loop                          (Slice 1)
  observability/  structured logging, metrics
frontend/src/
  api/            typed client generated from OpenAPI
  meeting/        live view                               (Slice 1)
  review/         summary, decisions, actions             (Slice 1)
```

Empty directories are deliberate: they are the module boundaries the
specification defines, and they get filled in slice order.

## What Slice 1 proves

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
