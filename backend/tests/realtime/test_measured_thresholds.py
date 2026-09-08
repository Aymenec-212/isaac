"""A-14 through the runtime: Slice 3's thresholds under real emission timing.

`test_measured_timing.py` checks the fixture and the recognizer. This file is
the one that matters for A-14: it drives the **real runtime** — gateway, pumps,
segmenter, persistence — with a recognizer whose emission timing came off an
actual MLX run, and asks whether reconnect, idle close and overload still behave.

Why this is not the same as the Slice 3 suite: those tests use
`FakeRecognizer`, which emits on a metronome. Every threshold they exercise was
chosen to absorb jitter, so testing them against no jitter is testing the easy
case. Here words arrive in bursts, with a 24-second hole in the middle — the
shape that actually provokes an idle close.

What this still does not answer, and does not claim to: real-time factor, memory
over hours, and long-run stability on MLX. Those need Apple silicon and are
Aymen's to run.
"""

from __future__ import annotations

import pytest

from mosaique.realtime.sessions import meeting as meeting_module
from mosaique.speech.adapters.fake import MeasuredRecognizer
from tests.integration.test_meeting_flow import create_and_join
from tests.realtime.test_reconnect import auth, hello, stream

pytestmark = pytest.mark.integration


@pytest.fixture
async def measured_client(engine):  # type: ignore[no-untyped-def]
    """The standard wiring, with real emission timing in place of the metronome."""
    from pathlib import Path

    from httpx import ASGITransport, AsyncClient

    from mosaique.app.main import create_app
    from mosaique.realtime.runtime_state import init_registry, shutdown_registry
    from mosaique.speech.audio import NullAudioStore
    from tests.conftest import WsClient

    recognizer = MeasuredRecognizer(loop_after_ms=66_000)
    init_registry(
        recognizer=recognizer,
        audio_root=Path("/tmp/mosaique-tests"),
        audio_store=NullAudioStore(),
    )
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield WsClient(http=http, app=app)
    await shutdown_registry()


async def test_a_meeting_transcribes_under_real_emission_timing(measured_client, settings, tenants):
    """The baseline: bursty arrival still produces an attributed transcript.

    825 frames is the whole 66 s fixture, including its 24-second silence. If
    the runtime only worked against evenly-spaced words, it would show here
    first.
    """
    token, meeting_id, joined = await create_and_join(
        measured_client.http, settings, tenants["alpha"]
    )

    async with measured_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await stream(ws, start=0, count=825)

    await measured_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

    body = (
        await measured_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    ).json()
    finals = [s for s in body["segments"] if s["status"] == "final"]

    assert finals, "real emission timing must still produce final segments"
    assert all(s["text"].strip() for s in finals), "no empty segment may be persisted"
    starts = [s["start_ms"] for s in finals]
    assert starts == sorted(starts), "the timeline must not go backwards under bursts"


async def test_the_fixtures_long_silence_does_not_look_like_a_dead_stream(
    measured_client, settings, tenants, monkeypatch
):
    """The case a metronome can never produce.

    The fixture contains 24 seconds during which the model emits nothing while
    audio keeps arriving. An idle close keyed to *events* rather than to frames
    would fire here and split the meeting's audio session in two. It is keyed to
    frames, and this test is what says so out loud.
    """
    monkeypatch.setattr(meeting_module, "IDLE_SWEEP_S", 0.05)

    token, meeting_id, joined = await create_and_join(
        measured_client.http, settings, tenants["alpha"]
    )
    participant_id = joined["participant"]["id"]

    async with measured_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        runtime = measured_client.registry.get(meeting_id)
        assert runtime is not None

        # Push through the silent stretch without pausing the stream.
        await stream(ws, start=0, count=200)
        opened = runtime._sessions[participant_id].audio_session_id  # noqa: SLF001
        await stream(ws, start=200, count=500)

        assert runtime._sessions[participant_id].audio_session_id == opened, (  # noqa: SLF001
            "audio kept arriving, so the session must not have been idle-closed"
        )

    await measured_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))


async def test_reconnect_mid_burst_keeps_the_transcript_whole(measured_client, settings, tenants):
    """A drop while the model owes us words (§7.4, X-13).

    With a metronome the reconnect always lands in the same place. Under real
    timing it lands mid-burst, with words already transcribed but not yet
    emitted — which is exactly when a resume that loses its place would show.
    """
    token, meeting_id, joined = await create_and_join(
        measured_client.http, settings, tenants["alpha"]
    )

    async with measured_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        next_seq = await stream(ws, start=0, count=120)

    # Reconnect and carry on from the same sequence.
    async with measured_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await stream(ws, start=next_seq, count=300)

    await measured_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

    body = (
        await measured_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    ).json()
    finals = [s for s in body["segments"] if s["status"] == "final"]

    assert finals, "a reconnect must not cost the whole transcript"
    sequences = [s["sequence"] for s in finals]
    assert len(sequences) == len(set(sequences)), "a resume must not duplicate segments"
    assert sequences == sorted(sequences)


async def test_ending_mid_burst_does_not_lose_words_the_model_already_owed(
    measured_client, settings, tenants
):
    """Finalization under real timing.

    Ending a meeting while words are pending is the normal case with a real
    model — there is always a ~500 ms tail. Those words have to reach the
    transcript, and only a flush that actually releases them makes that true.
    """
    token, meeting_id, joined = await create_and_join(
        measured_client.http, settings, tenants["alpha"]
    )

    async with measured_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await hello(ws, joined["session_token"])
        await stream(ws, start=0, count=150)  # 12 s in: a tail is always pending

    await measured_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

    body = (
        await measured_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    ).json()
    finals = [s for s in body["segments"] if s["status"] == "final"]

    assert finals, "the pending tail must be flushed into the transcript, not dropped"
