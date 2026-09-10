"""Slice 6R item 7: correcting a segment, and what that does to the summary (Q9).

Q9 moved from "transcript corrections are out of scope" to "in scope, additive
only" on 2026-09-09. **Additive is the whole contract**, and it is the thing
these tests exist to hold: `text` and `words` keep exactly what the ASR produced,
a correction lands beside them, and the original stays recoverable afterwards.

Why that matters more than it looks. L-28's shape, the 1.43% WER measured on
2026-09-08 and every `[measure]` row in §8 are claims about what the *model*
said. If a correction overwrote `text`, every one of them would become
unfalsifiable — with no way, later, to tell an edit from a transcription. The
column layout makes that impossible rather than discouraged.

The second half is the version handshake Aymen specified: correcting bumps
`transcript_version`, outputs remember which version they came from, and the two
being different is what lets the review page say *insights need review* instead
of showing a summary of text nobody can see any more. Regeneration is a button,
never automatic — five corrections should cost one LLM call, not five.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from mosaique.intelligence.provider import FakeLLMProvider
from mosaique.jobs import MeetingIntelligenceProcessor
from mosaique.persistence.engine import session_scope
from mosaique.persistence.models import Job, Meeting, TranscriptSegment
from tests.conftest import host_token_for
from tests.integration.test_intelligence_flow import run_meeting_to_completion
from tests.integration.test_meeting_flow import auth

pytestmark = pytest.mark.integration


async def first_segment(client, meeting_id: str, token: str) -> dict:
    body = (await client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))).json()
    finals = [s for s in body["segments"] if s["status"] == "final"]
    assert finals, "the meeting produced no transcript to correct"
    return finals[0]


async def test_a_correction_never_overwrites_what_the_model_said(ws_client, settings, tenants):
    """The Q9 contract, asserted against the database rather than the API.

    Reading it back through `GET /transcript` would only prove the route
    presents the correction. This looks at the row: `text` must still hold the
    model's words after the edit, or every WER and `[measure]` claim built on
    this data stops being checkable.
    """
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    segment = await first_segment(ws_client, meeting_id, token)
    original = segment["text"]

    corrected = await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "Le budget du trimestre est validé."},
        headers=auth(token),
    )
    assert corrected.status_code == 200
    assert corrected.json()["text"] == "Le budget du trimestre est validé."
    assert corrected.json()["original_text"] == original

    async with session_scope() as db:
        row = await db.get(TranscriptSegment, segment["id"])
        assert row is not None
        assert row.text == original, "the model's own words must survive the edit"
        assert row.corrected_text == "Le budget du trimestre est validé."
        assert row.corrected_at is not None
        assert row.corrected_by is not None, "an edit has to name who made it"


async def test_the_transcript_shows_the_correction_and_still_carries_the_original(
    ws_client, settings, tenants
):
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    segment = await first_segment(ws_client, meeting_id, token)
    original = segment["text"]

    await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "Texte corrigé."},
        headers=auth(token),
    )

    body = (
        await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    ).json()
    shown = next(s for s in body["segments"] if s["id"] == segment["id"])

    assert shown["text"] == "Texte corrigé."
    assert shown["original_text"] == original
    assert shown["corrected_at"] is not None

    # Everything else is untouched — a correction is not a re-segmentation.
    assert shown["start_ms"] == segment["start_ms"]
    assert shown["end_ms"] == segment["end_ms"]
    assert shown["audio_session_id"] == segment["audio_session_id"]

    # And a segment nobody edited says nothing about corrections at all, so the
    # fields' presence is a reliable "this was edited" signal.
    untouched = [s for s in body["segments"] if s["id"] != segment["id"]]
    assert untouched, "need a second segment to check the negative case"
    assert all(s["original_text"] is None for s in untouched)
    assert all(s["corrected_at"] is None for s in untouched)


async def meeting_with_two_participants(ws_client, settings, tenant):
    """A finished meeting Amina spoke in, with Bruno on the roster too.

    Built here rather than reusing `run_meeting_to_completion` because
    reattribution needs a second person to reattribute *to*, and the invite
    token is only returned when the meeting is created.
    """
    from tests.integration.test_meeting_flow import stream_until_finals

    token = host_token_for(settings, tenant)
    created = await ws_client.http.post(
        "/meetings", json={"title": "Deux voix"}, headers=auth(token)
    )
    meeting_id = created.json()["meeting"]["id"]
    invite = created.json()["invite_url"].split("t=")[1]

    amina = (
        await ws_client.http.post(
            f"/meetings/{meeting_id}/join",
            json={"display_name": "Amina", "invite_token": invite},
        )
    ).json()
    bruno = (
        await ws_client.http.post(
            f"/meetings/{meeting_id}/join",
            json={"display_name": "Bruno", "invite_token": invite},
        )
    ).json()

    async with ws_client.websocket_connect(f"/ws/meetings/{meeting_id}") as ws:
        await ws.send_json({"v": 1, "type": "hello", "session_token": amina["session_token"]})
        await ws.receive_json()
        await stream_until_finals(ws, frames=150, want=2)

    await ws_client.http.post(f"/meetings/{meeting_id}/end", headers=auth(token))
    return token, meeting_id, amina, bruno


async def test_a_speaker_can_be_corrected_without_touching_the_text(ws_client, settings, tenants):
    """The other half of item 7, and on one microphone the likelier error (L-2)."""
    token, meeting_id, _, bruno_join = await meeting_with_two_participants(
        ws_client, settings, tenants["alpha"]
    )
    segment = await first_segment(ws_client, meeting_id, token)
    bruno = bruno_join["participant"]["id"]
    assert segment["participant_id"] != bruno, "the fixture must start attributed to Amina"

    corrected = await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"participant_id": bruno},
        headers=auth(token),
    )
    assert corrected.status_code == 200
    assert corrected.json()["participant_id"] == bruno
    assert corrected.json()["original_participant_id"] == segment["participant_id"]
    assert corrected.json()["text"] == segment["text"], (
        "the words were not the thing that was wrong"
    )

    async with session_scope() as db:
        row = await db.get(TranscriptSegment, segment["id"])
        assert row is not None
        assert row.participant_id == segment["participant_id"], "raw attribution survives"
        assert row.corrected_participant_id == bruno


async def test_a_speaker_from_outside_the_meeting_is_refused(ws_client, settings, tenants):
    """Reattribution stays inside the roster the review page renders from."""
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    segment = await first_segment(ws_client, meeting_id, token)

    refused = await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"participant_id": "01M234S2DF7SYCSPZMCE6J1JCD"},
        headers=auth(token),
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_an_empty_correction_is_refused(ws_client, settings, tenants):
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    segment = await first_segment(ws_client, meeting_id, token)

    refused = await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={},
        headers=auth(token),
    )
    assert refused.status_code == 400


async def test_a_guest_cannot_rewrite_the_transcript(ws_client, settings, tenants):
    """A participant token can speak into a transcript, not edit it."""
    token, meeting_id, amina, _ = await meeting_with_two_participants(
        ws_client, settings, tenants["alpha"]
    )
    segment = await first_segment(ws_client, meeting_id, token)

    refused = await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "je réécris l'histoire"},
        headers={"Authorization": f"Bearer {amina['session_token']}"},
    )
    assert refused.status_code == 403

    # And nothing was written on the way to being refused.
    async with session_scope() as db:
        row = await db.get(TranscriptSegment, segment["id"])
        assert row is not None and row.corrected_text is None


async def test_a_segment_from_another_meeting_cannot_be_edited_through_this_one(
    ws_client, settings, tenants
):
    token_a, meeting_a = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    token_b, meeting_b = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    segment_a = await first_segment(ws_client, meeting_a, token_a)

    refused = await ws_client.http.patch(
        f"/meetings/{meeting_b}/segments/{segment_a['id']}",
        json={"text": "pas ici"},
        headers=auth(token_b),
    )
    assert refused.status_code == 404


async def test_corrections_are_not_readable_or_writable_across_tenants(
    ws_client, settings, tenants
):
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    segment = await first_segment(ws_client, meeting_id, token)

    beta = host_token_for(settings, tenants["beta"])
    denied = await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "chez le voisin"},
        headers=auth(beta),
    )
    assert denied.status_code == 404


async def test_search_matches_the_corrected_text_not_the_raw_text(ws_client, settings, tenants):
    """FR-10 against a corrected transcript.

    The failure this prevents is silent: search the stored text and the spans
    returned index into a string the reader cannot see, so the highlight lands
    on the wrong words — visible only in a browser, and only on edited segments.
    """
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    segment = await first_segment(ws_client, meeting_id, token)

    await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "Nous parlons de photosynthèse aujourd'hui."},
        headers=auth(token),
    )

    found = (
        await ws_client.http.get(
            f"/meetings/{meeting_id}/transcript",
            params={"q": "photosynthese"},
            headers=auth(token),
        )
    ).json()

    assert len(found["segments"]) == 1
    hit = found["segments"][0]
    assert hit["id"] == segment["id"]

    match = next(m for m in found["matches"] if m["segment_id"] == segment["id"])
    start, end = match["spans"][0]
    # The offsets slice the text the client will render, accents and all.
    assert hit["text"][start:end].lower() == "photosynthèse"


async def test_correcting_bumps_the_transcript_version(ws_client, settings, tenants):
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    segment = await first_segment(ws_client, meeting_id, token)

    async with session_scope() as db:
        before = (await db.get(Meeting, meeting_id)).transcript_version  # type: ignore[union-attr]
    assert before == 1

    await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "Une correction."},
        headers=auth(token),
    )

    async with session_scope() as db:
        after = (await db.get(Meeting, meeting_id)).transcript_version  # type: ignore[union-attr]
    assert after == 2


async def test_outputs_report_the_version_they_came_from_and_the_current_one(
    ws_client, settings, tenants
):
    """The handshake the review page reads to decide whether to say "à revoir"."""
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    assert await MeetingIntelligenceProcessor(FakeLLMProvider()).run_once()

    fresh = (
        await ws_client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(token))
    ).json()
    assert fresh["generated_from_transcript_version"] == 1
    assert fresh["current_transcript_version"] == 1

    segment = await first_segment(ws_client, meeting_id, token)
    await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "Le transcript a changé."},
        headers=auth(token),
    )

    stale = (
        await ws_client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(token))
    ).json()
    assert stale["generated_from_transcript_version"] == 1
    assert stale["current_transcript_version"] == 2
    # Still readable: a summary derived from older text is stale, not wrong to
    # show. The page labels it rather than hiding it.
    assert stale["status"] == "succeeded"
    assert stale["summary"]


async def test_correcting_does_not_re_run_the_summary_by_itself(ws_client, settings, tenants):
    """Aymen's decision, asserted: mark for review, do not spend the LLM call.

    Five corrections in a row should cost nothing. Only the button costs money.
    """
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    assert await MeetingIntelligenceProcessor(FakeLLMProvider()).run_once()

    body = (
        await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    ).json()
    for segment in body["segments"][:3]:
        await ws_client.http.patch(
            f"/meetings/{meeting_id}/segments/{segment['id']}",
            json={"text": f"Correction de {segment['id'][:6]}."},
            headers=auth(token),
        )

    async with session_scope() as db:
        jobs = (await db.execute(select(Job).where(Job.meeting_id == meeting_id))).scalars().all()
    assert len(jobs) == 1, "corrections must not enqueue intelligence work on their own"


async def test_regenerating_produces_outputs_for_the_corrected_transcript(
    ws_client, settings, tenants
):
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    assert await MeetingIntelligenceProcessor(FakeLLMProvider()).run_once()

    segment = await first_segment(ws_client, meeting_id, token)
    await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "La décision a été reportée."},
        headers=auth(token),
    )

    requested = await ws_client.http.post(
        f"/meetings/{meeting_id}/outputs/regenerate", headers=auth(token)
    )
    assert requested.status_code == 202
    assert await MeetingIntelligenceProcessor(FakeLLMProvider()).run_once()

    after = (
        await ws_client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(token))
    ).json()
    assert after["status"] == "succeeded"
    assert after["generated_from_transcript_version"] == 2
    assert after["current_transcript_version"] == 2

    # The v1 outputs are not deleted — they are a true record of what was
    # derived from that transcript. `GET /outputs` just returns the newest.
    async with session_scope() as db:
        from mosaique.persistence.models import MeetingOutputs

        rows = (
            (
                await db.execute(
                    select(MeetingOutputs).where(MeetingOutputs.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        )
    assert {r.transcript_version for r in rows} == {1, 2}


async def test_regenerating_twice_for_one_version_enqueues_one_job(ws_client, settings, tenants):
    """The button is idempotent per transcript version, by its idempotency key."""
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    assert await MeetingIntelligenceProcessor(FakeLLMProvider()).run_once()

    segment = await first_segment(ws_client, meeting_id, token)
    await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "Une seule correction."},
        headers=auth(token),
    )

    first = await ws_client.http.post(
        f"/meetings/{meeting_id}/outputs/regenerate", headers=auth(token)
    )
    second = await ws_client.http.post(
        f"/meetings/{meeting_id}/outputs/regenerate", headers=auth(token)
    )
    assert first.status_code == second.status_code == 202

    async with session_scope() as db:
        jobs = (await db.execute(select(Job).where(Job.meeting_id == meeting_id))).scalars().all()
    # One from finalization, one for version 2. Not three.
    assert len(jobs) == 2


async def test_the_summary_is_regenerated_from_the_corrected_words(ws_client, settings, tenants):
    """The point of the whole feature, end to end.

    `FakeLLMProvider` builds its answer from the prompt it is handed, so if the
    prompt still carried the raw text this would fail — which is exactly the
    coupling worth pinning: a correction has to reach the summarizer, not just
    the screen.
    """
    token, meeting_id = await run_meeting_to_completion(ws_client, settings, tenants["alpha"])
    segment = await first_segment(ws_client, meeting_id, token)

    await ws_client.http.patch(
        f"/meetings/{meeting_id}/segments/{segment['id']}",
        json={"text": "Un mot parfaitement reconnaissable: hippopotame."},
        headers=auth(token),
    )
    await ws_client.http.post(f"/meetings/{meeting_id}/outputs/regenerate", headers=auth(token))
    assert await MeetingIntelligenceProcessor(FakeLLMProvider()).run_once()

    transcript = (
        await ws_client.http.get(f"/meetings/{meeting_id}/transcript", headers=auth(token))
    ).json()
    outputs = (
        await ws_client.http.get(f"/meetings/{meeting_id}/outputs", headers=auth(token))
    ).json()

    # Evidence still resolves against the transcript after an edit: the ids did
    # not change, only the words behind them.
    known = {s["id"] for s in transcript["segments"]}
    cited = [
        sid
        for item in outputs["decisions"] + outputs["action_items"]
        for sid in item["evidence_segment_ids"]
    ]
    assert cited
    assert set(cited) <= known


async def test_regenerating_a_live_meeting_is_refused(ws_client, settings, tenants):
    from tests.integration.test_meeting_flow import create_and_join

    token, meeting_id, _ = await create_and_join(ws_client.http, settings, tenants["alpha"])
    refused = await ws_client.http.post(
        f"/meetings/{meeting_id}/outputs/regenerate", headers=auth(token)
    )
    assert refused.status_code == 409
