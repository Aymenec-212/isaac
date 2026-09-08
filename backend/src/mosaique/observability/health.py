"""Per-dependency health, and what readiness actually means (tech spec 15).

Three endpoints, three different questions, and the difference between them is
the whole design:

* `/livez` — is the process running? Touches nothing. Restart me if this fails.
* `/readyz` — could this instance take a meeting *right now*? Database reachable
  **and** ASR runtime ready. Stop sending traffic if this fails.
* `/health/deps` — what is the state of each dependency, individually? For a
  person diagnosing a bad run, not for a load balancer.

**The LLM provider is listed and does not affect readiness.** That is the spec's
call (§15) and it matches how the system actually behaves: a meeting records,
transcribes, segments and persists with no provider at all, and only the summary
is delayed — `test_a_failing_provider_leaves_transcript_and_meeting_untouched`
is the proof. Failing readiness on it would refuse meetings that would have
worked.

Everything here takes its probes as arguments. That is what lets each state —
including the ugly ones nobody can reproduce on demand — have a test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

DependencyState = Literal["ok", "degraded", "unavailable", "unknown"]

# A probe that hangs is worse than one that fails: the health endpoint is what
# gets called when things are already wrong, and it must answer then.
PROBE_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class DependencyHealth:
    name: str
    state: DependencyState
    detail: str
    # Whether this dependency's state decides `/readyz`. False for the LLM
    # provider, per §15 — carried as data rather than as an `if` in the route,
    # so the reason is visible in the response itself.
    gates_readiness: bool

    @property
    def blocks_readiness(self) -> bool:
        return self.gates_readiness and self.state != "ok"


Probe = Callable[[], Awaitable[DependencyHealth]]


async def _guarded(name: str, probe: Probe, *, gates_readiness: bool) -> DependencyHealth:
    """Run one probe so that no failure of its own can take the endpoint down."""
    try:
        return await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_S)
    except TimeoutError:
        return DependencyHealth(
            name=name,
            state="unavailable",
            detail=f"probe did not answer within {PROBE_TIMEOUT_S:g}s",
            gates_readiness=gates_readiness,
        )
    except Exception as exc:
        return DependencyHealth(
            name=name,
            # The dependency may be fine and the probe broken; either way this
            # instance cannot show that it works, which is what readiness asks.
            state="unavailable",
            detail=f"probe raised {type(exc).__name__}: {exc}",
            gates_readiness=gates_readiness,
        )


async def probe_all(probes: dict[str, tuple[Probe, bool]]) -> list[DependencyHealth]:
    """Run every probe concurrently and return them in a stable order.

    Concurrently because a health check during an outage would otherwise take
    the sum of every timeout; in a stable order because this output is read by
    a person comparing two runs.
    """
    names = sorted(probes)
    results = await asyncio.gather(
        *(_guarded(name, probes[name][0], gates_readiness=probes[name][1]) for name in names)
    )
    return list(results)


def is_ready(dependencies: list[DependencyHealth]) -> bool:
    """Ready when nothing that gates readiness is anything but `ok`."""
    return not any(d.blocks_readiness for d in dependencies)


def readiness_summary(dependencies: list[DependencyHealth]) -> str:
    """One line naming what is wrong, for the 503 body and for logs."""
    blocking = [d for d in dependencies if d.blocks_readiness]
    if not blocking:
        return "all dependencies that gate readiness are ok"
    return "; ".join(f"{d.name}: {d.state} ({d.detail})" for d in blocking)
