#!/usr/bin/env bash
set -euo pipefail

# Reusable local commands for the Mosaïque development workflow.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

stop_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)"
  if [[ -n "$pids" ]]; then
    # Stop only listeners on this project's application ports.
    while read -r pid; do
      [[ "$pid" =~ ^[0-9]+$ ]] && kill "$pid"
    done <<< "$pids"
  fi
}

case "${1:-help}" in
  db-up)
    # Start PostgreSQL in Docker and keep the data volume.
    cd "$ROOT"
    docker compose up -d postgres
    ;;
  db-stop)
    # Stop PostgreSQL without deleting its data volume.
    cd "$ROOT"
    docker compose stop postgres
    ;;
  backend)
    # Start the backend with the real local MLX runtime and configured LLM provider.
    cd "$ROOT/backend"
    MOSAIQUE_ASR_RUNTIME=mlx MOSAIQUE_LLM_PROVIDER=openai \
      uv run uvicorn mosaique.app.main:create_app --factory --host 127.0.0.1 --port 8000
    ;;
  backend-fake)
    # Start the deterministic fake backend for automated tests and browser specs.
    cd "$ROOT/backend"
    MOSAIQUE_ASR_RUNTIME=fake MOSAIQUE_LLM_PROVIDER=fake \
      uv run uvicorn mosaique.app.main:create_app --factory --host 127.0.0.1 --port 8000
    ;;
  frontend)
    # Start the Vite frontend at http://127.0.0.1:5173.
    cd "$ROOT/frontend"
    npm run dev -- --host 127.0.0.1 --port 5173
    ;;
  ready)
    # Show per-dependency readiness for the running backend.
    curl -fsS http://127.0.0.1:8000/readyz
    printf '\n'
    curl -fsS http://127.0.0.1:8000/health/deps
    printf '\n'
    ;;
  seed)
    # Print a development host token for the browser token gate.
    cd "$ROOT/backend"
    uv run python -m mosaique.app.seed
    ;;
  test-backend)
    # Run the complete backend suite serially with deterministic providers.
    cd "$ROOT/backend"
    MOSAIQUE_LLM_PROVIDER=fake MOSAIQUE_ASR_RUNTIME=fake uv run pytest -q
    ;;
  test-frontend)
    # Run frontend unit tests, typechecking, and the production build.
    cd "$ROOT/frontend"
    npm test -- --run
    npm run typecheck
    npm run build
    ;;
  test-e2e)
    # Run all Playwright browser specs against the running backend/frontend.
    cd "$ROOT/frontend"
    MOSAIQUE_HOST_TOKEN="$(
      cd ../backend
      uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}'
    )" npm run test:e2e
    ;;
  replay)
    # Replay a scenario through the real WebSocket gateway and write a report.
    cd "$ROOT/backend"
    uv run python -m tools.replay run tools/replay/scenarios/two-participants.json \
      --host-token "$(uv run python -m mosaique.app.seed | awk '/^host_token:/{print $2}')" \
      --speed 10 --report /tmp/mosaique-replay.json
    ;;
  stop)
    # Stop the local backend/frontend and PostgreSQL, preserving database data.
    stop_port 8000
    stop_port 5173
    cd "$ROOT"
    docker compose stop postgres
    ;;
  help|*)
    # List the available commands and their purpose.
    printf '%s\n' \
      'Usage: scripts/mosaique.sh <command>' \
      '  db-up         Start PostgreSQL' \
      '  db-stop       Stop PostgreSQL without deleting data' \
      '  backend       Start real MLX/OpenAI backend' \
      '  backend-fake  Start deterministic fake backend' \
      '  frontend      Start Vite frontend' \
      '  ready         Check backend dependency readiness' \
      '  seed          Print a development host token' \
      '  test-backend  Run backend tests' \
      '  test-frontend Run frontend tests, typecheck, and build' \
      '  test-e2e      Run Playwright browser specs' \
      '  replay        Run the two-participant replay harness' \
      '  stop          Stop backend, frontend, and PostgreSQL'
    ;;
esac
