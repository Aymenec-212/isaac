# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# uv is the package manager for this project; pip is not used anywhere.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Dependencies are their own layer so source edits do not reinstall the world.
COPY pyproject.toml uv.lock* ./
RUN uv venv && uv pip install --no-cache -r pyproject.toml

COPY src/ ./src/
COPY alembic.ini ./
COPY tools/ ./tools/

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 10001 mosaique && chown -R mosaique:mosaique /app
USER mosaique

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/livez',timeout=2).status==200 else 1)"

CMD ["uvicorn", "mosaique.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
