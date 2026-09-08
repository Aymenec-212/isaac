"""FR-11 end to end: a citation resolves to bytes of the right moment.

The unit tests pin the Range arithmetic and the store. This file checks the
things only a real request can: that tenancy holds on a new route, that a
browser's `Range` header comes back as 206 with the right headers, and that the
transcript payload carries what the review page needs to do the sum.

Runs against a `LocalAudioStore` rather than the suite's usual null one — the
route's whole subject is bytes that were kept.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mosaique.speech.audio.store import BYTES_PER_MS
from tests.conftest import host_token_for
from tests.integration.test_meeting_flow import auth, create_and_join, stream_until_finals

pytestmark = pytest.mark.integration


@pytest.fixture
async def recording_client(engine, tmp_path):  # type: ignore[no-untyped-def]
    """The standard wiring, but audio is written to disk instead of discarded."""
    from httpx import ASGITransport, AsyncClient

    from mosaique.app.main import create_app
    from mosaique.realtime.runtime_state import init_registry, shutdown_registry
    from mosaique.speech.adapters.fake import FakeRecognizer
    from mosaique.speech.audio import LocalAudioStore

    init_registry(
        recognizer=FakeRecognizer(),
        audio_root=tmp_path,
        audio_store=LocalAudioStore(tmp_path),
    )
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield _Recording(http=http, app=app, root=tmp_path)
    await shutdown_registry()


class _Recording:
    def __init__(self, http, app, root: Path) -> None:  # type: ignore[no-untyped-def]
        self.http = http
        self.app = app
        self.root = root

    def websocket_connect(self, path: str):  # type: ignore[no-untyped-def]
        from tests.conftest import ASGIWebSocket

        return ASGIWebSocket(self.app, path)


async def _meeting_with_audio(client, settings, tenant):  # type: ignore[no-untyped-def]
    token, meeting_id, joined = await create_and_join(client.http, settings, tenant)
    async with client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
        await ws.receive_json()
        await stream_until_finals(ws, frames=150, want=2)
    await client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))

    transcript = await client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    return token, meeting_id, transcript.json()


async def test_the_transcript_carries_what_a_citation_needs_to_be_played(
    recording_client, settings, tenants
):
    """A segment names its recording, and the recording names its epoch.

    Without both, a decision's evidence can be displayed but not played: the
    offset inside the file is `segment.start_ms - session.epoch_ms` and neither
    term is available anywhere else.
    """
    _, _, body = await _meeting_with_audio(recording_client, settings, tenants["alpha"])

    assert body["audio_sessions"], "the review page needs the session epochs"
    session_ids = {s["id"] for s in body["audio_sessions"]}
    spoken = [s for s in body["segments"] if s["status"] == "final"]
    assert spoken
    for segment in spoken:
        assert segment["audio_session_id"] in session_ids


async def test_a_whole_body_request_returns_the_stored_audio(recording_client, settings, tenants):
    token, meeting_id, body = await _meeting_with_audio(
        recording_client, settings, tenants["alpha"]
    )
    session_id = body["audio_sessions"][0]["id"]

    response = await recording_client.http.get(
        f"/meetings/{meeting_id}/audio/{session_id}", headers=auth(token)
    )

    assert response.status_code == 200
    # Without Accept-Ranges a browser never issues a second request, so the
    # scrub bar renders but seeking silently does nothing.
    assert response.headers["accept-ranges"] == "bytes"
    assert len(response.content) > 0
    assert len(response.content) % 2 == 0, "PCM is 16-bit; an odd length is a truncated sample"


async def test_a_range_request_returns_206_with_exactly_that_slice(
    recording_client, settings, tenants
):
    """What a media element does on every seek."""
    token, meeting_id, body = await _meeting_with_audio(
        recording_client, settings, tenants["alpha"]
    )
    session_id = body["audio_sessions"][0]["id"]
    url = f"/meetings/{meeting_id}/audio/{session_id}"

    whole = await recording_client.http.get(url, headers=auth(token))
    total = len(whole.content)

    # One second in, one second long — the shape of a citation jump.
    start = 1000 * BYTES_PER_MS
    end = start + 1000 * BYTES_PER_MS - 1
    partial = await recording_client.http.get(
        url, headers={**auth(token), "Range": f"bytes={start}-{end}"}
    )

    assert partial.status_code == 206
    assert partial.headers["content-range"] == f"bytes {start}-{end}/{total}"
    assert len(partial.content) == end - start + 1
    assert partial.content == whole.content[start : end + 1], "the slice must be the same bytes"


async def test_a_range_past_the_end_is_refused_with_the_total(recording_client, settings, tenants):
    token, meeting_id, body = await _meeting_with_audio(
        recording_client, settings, tenants["alpha"]
    )
    session_id = body["audio_sessions"][0]["id"]

    response = await recording_client.http.get(
        f"/meetings/{meeting_id}/audio/{session_id}",
        headers={**auth(token), "Range": "bytes=999999999-"},
    )

    assert response.status_code == 416
    assert response.headers["content-range"].startswith("bytes */")


async def test_audio_from_another_organization_is_not_reachable(
    recording_client, settings, tenants
):
    """Tenancy on a new route, checked rather than assumed (ADR-08)."""
    _, meeting_id, body = await _meeting_with_audio(recording_client, settings, tenants["alpha"])
    session_id = body["audio_sessions"][0]["id"]
    intruder = host_token_for(settings, tenants["beta"])

    response = await recording_client.http.get(
        f"/meetings/{meeting_id}/audio/{session_id}", headers=auth(intruder)
    )

    assert response.status_code == 404


async def test_an_unknown_session_is_not_found(recording_client, settings, tenants):
    token, meeting_id, _ = await _meeting_with_audio(recording_client, settings, tenants["alpha"])

    response = await recording_client.http.get(
        f"/meetings/{meeting_id}/audio/01JQBS7Q9Z8W2X3Y4Z5A6B7C8D", headers=auth(token)
    )

    assert response.status_code == 404


async def test_audio_is_not_served_without_a_token(recording_client, settings, tenants):
    _, meeting_id, body = await _meeting_with_audio(recording_client, settings, tenants["alpha"])
    session_id = body["audio_sessions"][0]["id"]

    response = await recording_client.http.get(f"/meetings/{meeting_id}/audio/{session_id}")

    assert response.status_code in {401, 403}
