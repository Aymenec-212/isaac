"""Health endpoints (tech spec 15).

Slice 0 ships /livez only. /readyz and /health/deps arrive in Slice 6, when
there are dependencies whose readiness actually means something.
"""

from __future__ import annotations

from fastapi import APIRouter

from mosaique import __version__
from mosaique.app.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/livez", response_model=HealthResponse)
async def livez() -> HealthResponse:
    """Process is up. Deliberately touches no dependency."""
    return HealthResponse(status="ok", version=__version__)
