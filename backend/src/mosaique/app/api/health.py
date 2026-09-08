"""Health endpoints (tech spec 15).

`/livez` says the process is up. `/readyz` says this instance could take a
meeting. `/health/deps` says what each dependency is doing. The three are
deliberately different questions — see `observability/health.py` for why, and
for why the LLM provider is listed but does not gate readiness.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from mosaique import __version__
from mosaique.app.api.dependencies import SettingsDep
from mosaique.app.api.schemas import (
    DependencyView,
    HealthResponse,
    ReadinessResponse,
)
from mosaique.config.settings import Settings
from mosaique.observability.health import (
    DependencyHealth,
    DependencyState,
    Probe,
    is_ready,
    probe_all,
    readiness_summary,
)
from mosaique.persistence.engine import session_scope
from mosaique.realtime.runtime_state import get_registry
from mosaique.speech.interfaces import ReadinessState

router = APIRouter(tags=["health"])

# How a runtime's own answer maps onto a dependency state. `unknown` stays
# `unknown` rather than collapsing to `unavailable`: "I have not checked" and
# "I checked and it is down" are different facts, and only one of them is a
# reason to page someone.
_ASR_STATE: dict[ReadinessState, DependencyState] = {
    "ready": "ok",
    "not_ready": "unavailable",
    "unknown": "unknown",
}


@router.get("/livez", response_model=HealthResponse)
async def livez() -> HealthResponse:
    """Process is up. Deliberately touches no dependency."""
    return HealthResponse(status="ok", version=__version__)


async def _probe_database() -> DependencyHealth:
    """One round trip. Enough to prove the pool can hand out a live connection."""
    async with session_scope() as db:
        await db.execute(text("SELECT 1"))
    return DependencyHealth(
        name="database",
        state="ok",
        detail="SELECT 1 returned",
        gates_readiness=True,
    )


def _probe_asr(settings: Settings) -> Probe:
    """Ask the recognizer, through the seam, rather than checking the config.

    Reading `settings.asr_runtime` would tell you what was *asked for*, which is
    not the question — and it would put the app-server back in the business of
    knowing which adapter it holds, which is the coupling the seam exists to
    prevent. `RecognizerReadiness` is on the `StreamingRecognizer` Protocol so
    every runtime answers for itself.
    """

    async def probe() -> DependencyHealth:
        readiness = await get_registry().recognizer.readiness()
        return DependencyHealth(
            name="asr_runtime",
            state=_ASR_STATE[readiness.state],
            detail=f"{settings.asr_runtime}: {readiness.detail}",
            # §15: readiness is "DB reachable AND ASR runtime reachable". An
            # `unknown` runtime therefore fails readiness rather than passing on
            # the benefit of the doubt.
            gates_readiness=True,
        )

    return probe


def _probe_llm(settings: Settings) -> Probe:
    """Report configuration, and say plainly that it is not a liveness check.

    Deliberately makes no network call. A real request costs money and adds a
    second of latency to an endpoint that gets polled, and the failure it would
    catch — the provider being down — does not stop a meeting from being
    recorded, transcribed and persisted. Only the summary waits.
    """

    async def probe() -> DependencyHealth:
        state: DependencyState
        if settings.llm_provider == "fake":
            detail = "fake provider; outputs are scripted, not generated"
            state = "degraded"
        elif not settings.llm_api_key:
            # Unreachable in practice — the settings validator refuses this at
            # startup — but stated rather than assumed.
            detail = f"{settings.llm_provider} selected with no api key"
            state = "unavailable"
        else:
            detail = (
                f"{settings.llm_provider} configured, model {settings.llm_model}; "
                "not probed (no request is made from a health check)"
            )
            state = "ok"
        return DependencyHealth(
            name="llm_provider",
            state=state,
            detail=detail,
            # §15: listed, but does not affect readiness. A meeting records and
            # transcribes without it; only the outputs are delayed.
            gates_readiness=False,
        )

    return probe


async def _dependencies(settings: Settings) -> list[DependencyHealth]:
    return await probe_all(
        {
            "database": (_probe_database, True),
            "asr_runtime": (_probe_asr(settings), True),
            "llm_provider": (_probe_llm(settings), False),
        }
    )


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(settings: SettingsDep, response: Response) -> ReadinessResponse:
    """Could this instance take a meeting right now? (tech spec 15.)

    503 when not, with the reason in the body — a load balancer needs the
    status code, and the person reading the logs afterwards needs the sentence.
    """
    dependencies = await _dependencies(settings)
    ready = is_ready(dependencies)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        version=__version__,
        summary=readiness_summary(dependencies),
        dependencies=[DependencyView.model_validate(d, from_attributes=True) for d in dependencies],
    )


@router.get("/health/deps", response_model=ReadinessResponse)
async def health_deps(settings: SettingsDep) -> ReadinessResponse:
    """Per-dependency detail. Always 200 — this endpoint reports, it does not judge.

    Separate from `/readyz` because they are read by different things: a load
    balancer wants a status code, and a person wants to know which of three
    dependencies is the one that is broken.
    """
    dependencies = await _dependencies(settings)
    return ReadinessResponse(
        status="ready" if is_ready(dependencies) else "not_ready",
        version=__version__,
        summary=readiness_summary(dependencies),
        dependencies=[DependencyView.model_validate(d, from_attributes=True) for d in dependencies],
    )
