"""Readiness logic, without a server (tech spec 15).

The interesting states of a health endpoint are the ones you cannot produce on
demand — a probe that hangs, a probe that raises, a dependency that is down but
does not gate readiness. `observability/health.py` takes its probes as arguments
precisely so each of those has a test here rather than a hopeful comment.
"""

from __future__ import annotations

import asyncio

import pytest

from mosaique.observability.health import (
    DependencyHealth,
    is_ready,
    probe_all,
    readiness_summary,
)


def _health(name: str, state: str, *, gates: bool = True) -> DependencyHealth:
    return DependencyHealth(
        name=name,
        state=state,  # type: ignore[arg-type]
        detail=f"{name} is {state}",
        gates_readiness=gates,
    )


def _probe(result: DependencyHealth):  # type: ignore[no-untyped-def]
    async def run() -> DependencyHealth:
        return result

    return run


# --- what readiness means --------------------------------------------------


def test_everything_ok_is_ready():
    assert is_ready([_health("database", "ok"), _health("asr_runtime", "ok")])


def test_a_gating_dependency_that_is_down_blocks_readiness():
    assert not is_ready([_health("database", "unavailable"), _health("asr_runtime", "ok")])


def test_an_unknown_gating_dependency_blocks_readiness():
    """"I have not checked" is not "it is fine".

    This is the case that keeps `moshi_server` honest: it reports `unknown`
    because nobody has ever reached one, and readiness must not paper over that
    until Slice 6B implements a real probe.
    """
    assert not is_ready([_health("asr_runtime", "unknown")])


def test_a_failing_llm_provider_does_not_block_readiness():
    """Tech spec 15, and it matches how the system behaves.

    A meeting records, transcribes, segments and persists with no provider at
    all — only the summary waits. Failing readiness here would refuse meetings
    that would have worked.
    """
    dependencies = [
        _health("database", "ok"),
        _health("asr_runtime", "ok"),
        _health("llm_provider", "unavailable", gates=False),
    ]

    assert is_ready(dependencies)


def test_the_summary_names_only_what_actually_blocks():
    dependencies = [
        _health("database", "ok"),
        _health("asr_runtime", "unavailable"),
        _health("llm_provider", "unavailable", gates=False),
    ]

    summary = readiness_summary(dependencies)

    assert "asr_runtime" in summary
    assert "llm_provider" not in summary, "a non-gating dependency is not the blocker"


def test_the_summary_says_so_when_nothing_is_wrong():
    assert "ok" in readiness_summary([_health("database", "ok")])


# --- probes that misbehave -------------------------------------------------


@pytest.mark.asyncio
async def test_a_probe_that_raises_becomes_unavailable_rather_than_a_500():
    """The endpoint has to answer *especially* when things are broken."""

    async def exploding() -> DependencyHealth:
        raise RuntimeError("connection pool exhausted")

    results = await probe_all({"database": (exploding, True)})

    assert results[0].state == "unavailable"
    assert "RuntimeError" in results[0].detail
    assert "connection pool exhausted" in results[0].detail


@pytest.mark.asyncio
async def test_a_probe_that_hangs_times_out_instead_of_hanging_the_endpoint(monkeypatch):
    """A health check that blocks is worse than one that fails.

    An unreachable database typically hangs rather than refusing, so this is
    the realistic outage shape, not an exotic one.
    """
    monkeypatch.setattr("mosaique.observability.health.PROBE_TIMEOUT_S", 0.05)

    async def hangs() -> DependencyHealth:
        await asyncio.sleep(10)
        raise AssertionError("unreachable")

    results = await probe_all({"database": (hangs, True)})

    assert results[0].state == "unavailable"
    assert "did not answer" in results[0].detail


@pytest.mark.asyncio
async def test_one_broken_probe_does_not_hide_the_others():
    """Diagnosis needs every dependency's state, not just the first failure."""

    async def exploding() -> DependencyHealth:
        raise RuntimeError("nope")

    results = await probe_all(
        {
            "asr_runtime": (exploding, True),
            "database": (_probe(_health("database", "ok")), True),
            "llm_provider": (_probe(_health("llm_provider", "ok", gates=False)), False),
        }
    )

    assert [r.name for r in results] == ["asr_runtime", "database", "llm_provider"]
    assert [r.state for r in results] == ["unavailable", "ok", "ok"]


@pytest.mark.asyncio
async def test_probes_run_concurrently_rather_than_in_sequence(monkeypatch):
    """During an outage, sequential probes would cost the sum of every timeout."""
    monkeypatch.setattr("mosaique.observability.health.PROBE_TIMEOUT_S", 0.5)

    async def slow(name: str) -> DependencyHealth:
        await asyncio.sleep(0.1)
        return _health(name, "ok")

    started = asyncio.get_running_loop().time()
    await probe_all(
        {
            "a": (lambda: slow("a"), True),
            "b": (lambda: slow("b"), True),
            "c": (lambda: slow("c"), True),
        }
    )
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.25, f"three 0.1s probes took {elapsed:.2f}s; they ran in sequence"


@pytest.mark.asyncio
async def test_results_keep_a_stable_order_whatever_the_probes_do(monkeypatch):
    """This output gets compared between runs by a person."""
    monkeypatch.setattr("mosaique.observability.health.PROBE_TIMEOUT_S", 0.5)

    async def quick(name: str) -> DependencyHealth:
        return _health(name, "ok")

    async def slower(name: str) -> DependencyHealth:
        await asyncio.sleep(0.05)
        return _health(name, "ok")

    results = await probe_all(
        {
            "zebra": (lambda: quick("zebra"), True),
            "alpha": (lambda: slower("alpha"), True),
        }
    )

    assert [r.name for r in results] == ["alpha", "zebra"]
