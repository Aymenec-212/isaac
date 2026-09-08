"""`/livez`, `/readyz`, `/health/deps` against a real app (tech spec 15).

Phase A's reason for building these: when a local meeting goes wrong, the first
question is *which* dependency broke. These tests check the endpoints answer
that question rather than a single unhelpful boolean.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _by_name(body: dict) -> dict[str, dict]:
    return {d["name"]: d for d in body["dependencies"]}


async def test_livez_says_nothing_about_dependencies(client):
    """It answers even when everything downstream is on fire — that is its job."""
    response = await client.get("/livez")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "dependencies" not in response.json()


async def test_readyz_is_ready_with_a_live_database_and_a_ready_runtime(client):
    response = await client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert _by_name(body)["database"]["state"] == "ok"
    assert _by_name(body)["asr_runtime"]["state"] == "ok"


async def test_health_deps_lists_every_dependency_separately(client):
    """The diagnostic endpoint. Three dependencies, three independent answers."""
    response = await client.get("/health/deps")

    assert response.status_code == 200
    dependencies = _by_name(response.json())
    assert set(dependencies) == {"database", "asr_runtime", "llm_provider"}
    for entry in dependencies.values():
        assert entry["detail"], "a state with no detail cannot be diagnosed"


async def test_the_llm_provider_is_listed_but_does_not_gate_readiness(client):
    """Tech spec 15, carried in the response so the reason is visible.

    A meeting records, transcribes and persists with no provider; only the
    summary waits. The flag is data rather than an `if` in the route precisely
    so a reader can see why a degraded provider left the instance ready.
    """
    body = (await client.get("/health/deps")).json()
    dependencies = _by_name(body)

    assert dependencies["llm_provider"]["gates_readiness"] is False
    assert dependencies["database"]["gates_readiness"] is True
    assert dependencies["asr_runtime"]["gates_readiness"] is True


async def test_the_test_suite_runs_on_a_fake_provider_and_says_so(client):
    """Honest about itself: scripted outputs are not generated ones.

    `degraded` rather than `ok`, because someone reading this endpoint on a
    machine they thought was configured for OpenAI should see the discrepancy.
    """
    dependencies = _by_name((await client.get("/health/deps")).json())

    assert dependencies["llm_provider"]["state"] == "degraded"
    assert "fake" in dependencies["llm_provider"]["detail"]


async def test_readyz_reports_503_and_names_the_blocker_when_the_runtime_is_not_ready(
    client, monkeypatch
):
    """The case the endpoint exists for.

    A recognizer that cannot take a meeting must make the instance unready, and
    the response has to say which dependency it was — that sentence is the
    difference between a five-minute fix and an hour of guessing.
    """
    from mosaique.realtime.runtime_state import get_registry
    from mosaique.speech.interfaces import RecognizerReadiness

    async def not_ready() -> RecognizerReadiness:
        return RecognizerReadiness(state="not_ready", detail="metal out of memory")

    monkeypatch.setattr(get_registry().recognizer, "readiness", not_ready, raising=False)

    response = await client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert "asr_runtime" in body["summary"]
    assert "metal out of memory" in body["summary"]


async def test_an_unknown_runtime_is_not_ready_either(client, monkeypatch):
    """`moshi_server`'s state today: never probed, so never vouched for.

    This is what keeps the production serving path from reading as verified
    before Slice 6B has actually served a meeting through it.
    """
    from mosaique.realtime.runtime_state import get_registry
    from mosaique.speech.interfaces import RecognizerReadiness

    async def unknown() -> RecognizerReadiness:
        return RecognizerReadiness(state="unknown", detail="never probed")

    monkeypatch.setattr(get_registry().recognizer, "readiness", unknown, raising=False)

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert _by_name(response.json())["asr_runtime"]["state"] == "unknown"


async def test_health_deps_still_answers_200_when_a_dependency_is_down(client, monkeypatch):
    """It reports; it does not judge.

    `/readyz` is the one that returns 503. If this endpoint also failed, the
    diagnostic tool would go dark exactly when it is needed.
    """
    from mosaique.realtime.runtime_state import get_registry
    from mosaique.speech.interfaces import RecognizerReadiness

    async def not_ready() -> RecognizerReadiness:
        return RecognizerReadiness(state="not_ready", detail="down")

    monkeypatch.setattr(get_registry().recognizer, "readiness", not_ready, raising=False)

    response = await client.get("/health/deps")

    assert response.status_code == 200
    assert response.json()["status"] == "not_ready"


async def test_a_probe_that_raises_does_not_take_the_endpoint_down(client, monkeypatch):
    """The endpoint must survive its own probes failing."""
    from mosaique.realtime.runtime_state import get_registry

    async def explodes():  # type: ignore[no-untyped-def]
        raise RuntimeError("registry is confused")

    monkeypatch.setattr(get_registry().recognizer, "readiness", explodes, raising=False)

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert "RuntimeError" in _by_name(response.json())["asr_runtime"]["detail"]


async def test_health_endpoints_need_no_token(client):
    """A load balancer has no credentials, and neither does a person debugging.

    Safe because nothing here carries meeting content — only dependency names,
    states, and the configured model. Worth stating: the rest of the API is
    tenant-scoped and this is the deliberate exception.
    """
    for path in ("/livez", "/readyz", "/health/deps"):
        assert (await client.get(path)).status_code in {200, 503}
