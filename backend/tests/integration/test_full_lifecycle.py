"""One meeting, end to end: create → join → speak → end → finalize → summarize → review.

**Why this file exists.** Every step below already had a passing test before it
was written. What none of them had was a test that the steps *compose*: the
suite proved seven things separately and nothing proved they add up to a
meeting a person can read afterwards. The failures this shape catches are the
ones that live in the joins — a segment that persists but carries no
`audio_session_id`, evidence ids the summarizer cites that the transcript route
does not return, an epoch that makes a citation seek past the end of its own
recording. Each of those passes every narrow test and breaks the product.

**Why `MeasuredRecognizer` and not `FakeRecognizer`.** The scripted fake emits
on a metronome and always says the same short line. Neither is what a lifecycle
has to survive: the review page's citations resolve against segment boundaries,
and boundaries are exactly what changes when words arrive in bursts. This
replays the emission timing of a real MLX run — p50 320 ms between words, p95
1 280 ms, one 24-second hole — over the real French of the B1 fixture, so the
transcript this asserts on has the shape a real one does (A-14, `measured.py`).

**Why a `LocalAudioStore`.** The suite's usual `NullAudioStore` discards bytes,
which makes the last leg of FR-11 unfalsifiable: a citation would resolve to an
offset nobody can check. Writing the audio means the test can ask the question
that matters — does the byte range this citation names actually exist inside
that recording.

**What this is not.** ✅ fake, and only fake. No model runs here and no provider
is called: `MeasuredRecognizer` loads no weights and `FakeLLMProvider` is not a
language model. This proves the *chain* holds under realistic timing. It says
nothing about real-time factor, memory over hours, MLX stability, or whether
OpenAI accepts the request body — those need Apple silicon or a key and are
Aymen's to run (§12).
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from pathlib import Path

import pytest
from sqlalchemy import select

from mosaique.intelligence.provider import FakeLLMProvider
from mosaique.jobs import MeetingIntelligenceProcessor
from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import AudioSession, Job, Meeting, TranscriptSegment
from mosaique.realtime.protocol.frames import encode_frame
from mosaique.speech.adapters.fake.measured import MEASURED_IDENTITY
from mosaique.speech.audio.store import BYTES_PER_MS
from mosaique.transcript.search import MIN_QUERY_LENGTH
from tests.conftest import host_token_for

pytestmark = pytest.mark.integration

PCM = b"\x00\x01" * 1920  # 80 ms of canonical 24 kHz s16 mono

# The whole B1 fixture is 66 s; 825 frames is all of it, silence included. Less
# than that and the long hole never arrives, which is the part of the timing no
# metronome can produce.
FIXTURE_FRAMES = 825


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def strip_accents(text: str) -> str:
    """What a person types when they cannot be bothered with a keyboard layout."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


@pytest.fixture
async def lifecycle_client(engine, tmp_path):  # type: ignore[no-untyped-def]
    """The product's real wiring, with measured ASR timing and audio kept on disk."""
    from httpx import ASGITransport, AsyncClient

    from mosaique.app.main import create_app
    from mosaique.realtime.runtime_state import init_registry, shutdown_registry
    from mosaique.speech.adapters.fake import MeasuredRecognizer
    from mosaique.speech.audio import LocalAudioStore

    init_registry(
        recognizer=MeasuredRecognizer(),
        audio_root=tmp_path,
        audio_store=LocalAudioStore(tmp_path),
    )
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield _Lifecycle(http=http, app=app, root=tmp_path)
    await shutdown_registry()


class _Lifecycle:
    def __init__(self, http, app, root: Path) -> None:  # type: ignore[no-untyped-def]
        self.http = http
        self.app = app
        self.root = root

    def websocket_connect(self, path: str):  # type: ignore[no-untyped-def]
        from tests.conftest import ASGIWebSocket

        return ASGIWebSocket(self.app, path)

    @property
    def registry(self):  # type: ignore[no-untyped-def]
        from mosaique.realtime.runtime_state import get_registry

        return get_registry()


async def speak(ws, *, frames: int, batch: int = 25) -> list[dict]:
    """Stream `frames` frames of audio, collecting whatever the server says back.

    Batched with a yield between batches on purpose. A tight send loop holding
    the socket looks exactly like a dead client to the stale-socket rule
    (§7.4) — the trap the replay harness fell into — and it also starves the
    reader task that turns pushed audio into words, which would make this test
    assert on a transcript the runtime never had a chance to produce.
    """
    heard: list[dict] = []
    for start in range(0, frames, batch):
        for seq in range(start, min(start + batch, frames)):
            await ws.send_bytes(encode_frame(seq, seq * 80, PCM))
        await asyncio.sleep(0.02)
        heard.extend(ws.drain())
    await asyncio.sleep(0.3)
    heard.extend(ws.drain())
    return heard


async def test_a_meeting_runs_from_creation_to_a_reviewable_record(
    lifecycle_client, settings, tenants
):
    """The whole chain, once, with every join between the steps asserted.

    Read the step comments as the contract: each one names what the *next* step
    depends on, because that dependency is the thing a narrow test cannot see.
    """
    client = lifecycle_client
    host_token = host_token_for(settings, tenants["alpha"])

    # ---- 1. create -------------------------------------------------------
    created = await client.http.post(
        "/meetings", json={"title": "Point hebdomadaire"}, headers=auth(host_token)
    )
    assert created.status_code == 201
    body = created.json()
    meeting_id = body["meeting"]["id"]
    # A room nobody has spoken in yet. The JOINABLE -> LIVE transition belongs
    # to the first accepted audio, not to the host pressing create — asserted
    # again at the `hello` below, which is where it actually happens.
    assert body["meeting"]["state"] == "JOINABLE"
    invite_token = body["invite_url"].split("t=")[1]

    # ---- 2. join ---------------------------------------------------------
    # A guest never sees the host token. Everything after this point is done
    # with what the invite actually yields.
    joined = await client.http.post(
        f"/meetings/{meeting_id}/join",
        json={"display_name": "Amina", "invite_token": invite_token},
    )
    assert joined.status_code == 200
    join = joined.json()
    participant_id = join["participant"]["id"]
    assert join["ws_url"] == f"/ws/meetings/{meeting_id}"

    # ---- 3. speak --------------------------------------------------------
    async with client.websocket_connect(join["ws_url"]) as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": join["session_token"]})
        hello_ok = await ws.receive_json()
        assert hello_ok["type"] == "hello.ok"
        assert hello_ok["meeting_state"] == "LIVE"

        heard = await speak(ws, frames=FIXTURE_FRAMES)

        # The live half has to have happened, not just the durable half. A run
        # that persisted a perfect transcript while broadcasting nothing is a
        # product nobody watched work.
        live_deltas = [m for m in heard if m["type"] == "transcript.delta"]
        live_finals = [m for m in heard if m["type"] == "transcript.segment.final"]
        assert live_deltas, "no interim transcript ever reached the participant"
        assert live_finals, "no final segment was broadcast while the meeting was live"
        assert all(m["participant_id"] == participant_id for m in live_deltas + live_finals), (
            "every broadcast segment must be attributed to the speaker"
        )

        # ---- 4. end ------------------------------------------------------
        # Ended from the host's token, over HTTP, while the participant's socket
        # is still open — which is what a real meeting looks like, and the only
        # arrangement in which step 6's notification has anywhere to go.
        ended = await client.http.post(f"/meetings/{meeting_id}/end", headers=auth(host_token))
        assert ended.status_code == 200
        assert ended.json()["meeting"]["state"] == "COMPLETED"
        ws.drain()

        # ---- 5. finalize -------------------------------------------------
        async with session_scope() as db:
            meeting = await db.get(Meeting, meeting_id)
            assert meeting is not None
            assert meeting.state == "COMPLETED"
            assert meeting.transcript_version == 1
            assert meeting.ended_at is not None
            # ADR-13 §3: the transcript names what produced it. This one was
            # produced by a fake, and the record says so rather than leaving a
            # NULL that a later reader could mistake for a model's work.
            assert meeting.asr_version == MEASURED_IDENTITY.truncated()

            rows = (
                (
                    await db.execute(
                        select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
                    )
                )
                .scalars()
                .all()
            )
            audio_rows = (
                (
                    await db.execute(
                        select(AudioSession).where(AudioSession.meeting_id == meeting_id)
                    )
                )
                .scalars()
                .all()
            )
            jobs = (
                (await db.execute(select(Job).where(Job.meeting_id == meeting_id))).scalars().all()
            )

        assert rows, "the meeting ended with nothing durable to review"
        assert all(r.status == "final" for r in rows), "ADR-05: only finals are persisted"
        assert len(audio_rows) == 1, "one uninterrupted stream is one audio session"
        assert audio_rows[0].frames_received > 0
        assert len(jobs) == 1, "ending a meeting enqueues exactly one intelligence job"

        # ---- 6. summarize ------------------------------------------------
        # Driven by hand rather than by the polling loop, so the assertion below
        # is about the processor and not about how long the test was willing to
        # wait.
        processor = MeetingIntelligenceProcessor(
            FakeLLMProvider(), broadcaster=client.registry.broadcaster
        )
        assert await processor.run_once(), "the job the end enqueued was never claimed"

        await asyncio.sleep(0.05)
        assert any(m.get("type") == "meeting.outputs.ready" for m in ws.drain()), (
            "nobody told the participant still on the page that the summary existed"
        )

    # ---- 7. review -------------------------------------------------------
    transcript = await client.http.get(
        f"/meetings/{meeting_id}/transcript", headers=auth(host_token)
    )
    assert transcript.status_code == 200
    review = transcript.json()

    outputs = await client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(host_token))
    assert outputs.status_code == 200
    derived = outputs.json()
    assert derived["status"] == "succeeded"
    assert derived["summary"], "a review page with no summary is the failure this step exists for"
    assert derived["decisions"] and derived["action_items"]

    segments = {s["id"]: s for s in review["segments"]}
    sessions = {a["id"]: a for a in review["audio_sessions"]}
    assert segments and sessions

    speakers = {p["id"] for p in review["participants"]}
    assert participant_id in speakers, "the review page cannot name who spoke"
    assert all(s["participant_id"] in speakers for s in review["segments"])

    # The timeline reads forwards. Under bursty emission this is the assertion
    # that would fail if stream time were ever confused for wall time (ADR-11).
    starts = [s["start_ms"] for s in review["segments"]]
    assert starts == sorted(starts)

    # Every citation the summarizer produced resolves the way `evidence.ts`
    # resolves it, and lands inside a recording that really holds those bytes.
    cited = [
        segment_id
        for item in derived["decisions"] + derived["action_items"] + derived["open_questions"]
        for segment_id in item["evidence_segment_ids"]
    ]
    assert cited, "outputs with no evidence are not reviewable (tech spec 12.3)"

    for segment_id in cited:
        assert segment_id in segments, f"cited segment {segment_id} is not in the transcript"
        segment = segments[segment_id]
        session_id = segment["audio_session_id"]
        assert session_id in sessions, "a cited segment must name a recording that was returned"
        offset_ms = segment["start_ms"] - sessions[session_id]["epoch_ms"]
        assert offset_ms >= 0, "a citation cannot start before its own recording"

        audio = await client.http.get(
            f"/meetings/{meeting_id}/audio/{session_id}", headers=auth(host_token)
        )
        assert audio.status_code == 200
        assert offset_ms * BYTES_PER_MS < len(audio.content), (
            "the citation seeks past the end of the recording it points into"
        )

    # One real seek, the way a browser does it: Range at the first citation.
    first = segments[cited[0]]
    session = sessions[first["audio_session_id"]]
    url = f"/meetings/{meeting_id}/audio/{first['audio_session_id']}"
    whole = await client.http.get(url, headers=auth(host_token))
    start = (first["start_ms"] - session["epoch_ms"]) * BYTES_PER_MS
    end = min(start + 1000 * BYTES_PER_MS, len(whole.content)) - 1
    played = await client.http.get(
        url, headers={**auth(host_token), "Range": f"bytes={start}-{end}"}
    )
    assert played.status_code == 206
    assert played.content == whole.content[start : end + 1]

    # Search finds the moment again (FR-10), and finds it without accents —
    # the deliberate deviation from §6's ILIKE, and the reason it was made.
    # The longest accented word rather than the first: `à` is a word too, and a
    # query below `MIN_QUERY_LENGTH` is answered with the whole transcript, so
    # picking it would make this leg pass while proving nothing.
    words = re.findall(r"\w+", " ".join(s["text"] for s in review["segments"]), flags=re.UNICODE)
    accented = max((w for w in words if strip_accents(w) != w), key=len, default="")
    assert len(accented) >= MIN_QUERY_LENGTH, (
        "no accented word long enough to search: either the transcript is not "
        "French any more, or this leg is silently testing an unfiltered read"
    )
    query = strip_accents(accented)

    found = await client.http.get(
        f"/meetings/{meeting_id}/transcript",
        params={"q": query},
        headers=auth(host_token),
    )
    assert found.status_code == 200
    hits = found.json()
    assert hits["query"] == query
    assert hits["segments"], f"searching {query!r} found nothing"
    assert len(hits["segments"]) <= len(review["segments"]), "a search must not invent segments"
    # "3 of 30" needs both numbers, and the denominator is the unfiltered count.
    assert hits["total_segments"] == len(review["segments"])
    assert hits["matches"], "a match with no offsets cannot be highlighted"
    assert any(accented in s["text"] for s in hits["segments"]), (
        f"searching {query!r} returned segments that do not contain {accented!r}"
    )


async def test_two_meetings_in_a_row_do_not_contaminate_each_other(
    lifecycle_client, settings, tenants
):
    """Slice 6A's bar is *repeatedly*, not once.

    The runtime is process-global — one registry, one recognizer, one broadcaster
    — and the pumps that touch it are per-participant tasks sharing state across
    awaits, which is where this codebase has already lost a segment once. A
    second meeting through the same process is the cheapest thing that would
    notice a runtime carrying the first one's state into it.
    """
    client = lifecycle_client
    host_token = host_token_for(settings, tenants["alpha"])
    seen: list[tuple[str, set[str]]] = []

    for title in ("Première réunion", "Deuxième réunion"):
        created = await client.http.post(
            "/meetings", json={"title": title}, headers=auth(host_token)
        )
        meeting_id = created.json()["meeting"]["id"]
        invite = created.json()["invite_url"].split("t=")[1]
        joined = (
            await client.http.post(
                f"/meetings/{meeting_id}/join",
                json={"display_name": "Amina", "invite_token": invite},
            )
        ).json()

        async with client.websocket_connect(joined["ws_url"]) as ws:
            await ws.send_json({"v": 1, "type": "hello", "session_token": joined["session_token"]})
            await ws.receive_json()
            await speak(ws, frames=200)

        await client.http.post(f"/meetings/{meeting_id}/end", headers=auth(host_token))
        assert await MeetingIntelligenceProcessor(FakeLLMProvider()).run_once()

        review = (
            await client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(host_token))
        ).json()
        outputs = await client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(host_token))
        assert outputs.status_code == 200, f"{title} produced no outputs"
        assert review["segments"], f"{title} produced no transcript"
        seen.append((meeting_id, {s["id"] for s in review["segments"]}))

    (first_id, first_segments), (second_id, second_segments) = seen
    assert first_id != second_id
    assert not (first_segments & second_segments), "a segment was served under two meetings"

    # The second meeting starts its own timeline rather than resuming the first's.
    async with session_scope() as db:
        sessions = (
            (await db.execute(select(AudioSession).where(AudioSession.meeting_id == second_id)))
            .scalars()
            .all()
        )
    assert len(sessions) == 1
    assert sessions[0].epoch_ms < 5_000, "the second meeting inherited the first one's anchor"
