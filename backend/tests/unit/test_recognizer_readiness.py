"""`StreamingRecognizer.readiness()` — the seam's answer to `/readyz`.

The point of putting readiness on the Protocol is that the app-server never has
to know which adapter it holds. These tests check each runtime answers honestly
for itself, and — the case that matters most — that a runtime which has *not*
been checked says so rather than claiming to be fine.
"""

from __future__ import annotations

import pytest

from mosaique.speech.adapters.fake import FakeRecognizer
from mosaique.speech.adapters.kyutai import KyutaiRecognizer
from mosaique.speech.interfaces import RecognizerReadiness, StreamingRecognizer


class _Backend:
    """Enough of `KyutaiBackend` for the recognizer to hold and warm."""

    def __init__(self, *, warms: bool = True, fails: Exception | None = None) -> None:
        self._fails = fails
        if warms:
            self.preload = self._preload  # type: ignore[method-assign]

    async def _preload(self) -> None:
        if self._fails is not None:
            raise self._fails


def test_both_recognizers_satisfy_the_protocol_including_readiness():
    """The seam only holds if every implementation answers the same questions."""
    assert isinstance(FakeRecognizer(), StreamingRecognizer)
    assert isinstance(KyutaiRecognizer(lambda: _Backend()), StreamingRecognizer)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_the_fake_is_ready_immediately():
    readiness = await FakeRecognizer().readiness()

    assert readiness.state == "ready"
    assert readiness.ready


@pytest.mark.asyncio
async def test_a_kyutai_runtime_that_has_not_preloaded_is_unknown_not_ready():
    """Before warm-up nothing has been proven, and `unknown` says exactly that.

    `/readyz` treats unknown as not-ready, so an instance that has not finished
    loading its weights refuses traffic instead of accepting a meeting it cannot
    transcribe.
    """
    readiness = await KyutaiRecognizer(lambda: _Backend()).readiness()  # type: ignore[arg-type]

    assert readiness.state == "unknown"
    assert not readiness.ready
    assert "preload has not run" in readiness.detail


@pytest.mark.asyncio
async def test_a_kyutai_runtime_is_ready_once_its_weights_are_loaded():
    recognizer = KyutaiRecognizer(lambda: _Backend())  # type: ignore[arg-type]

    await recognizer.preload()
    readiness = await recognizer.readiness()

    assert readiness.state == "ready"
    assert "weights loaded" in readiness.detail


@pytest.mark.asyncio
async def test_a_failed_preload_is_reported_with_its_reason():
    """The failure `/readyz` exists for: a model that would not load.

    The reason belongs in the response, not only in a log line read after
    someone has already tried to hold a meeting.
    """
    recognizer = KyutaiRecognizer(  # type: ignore[arg-type]
        lambda: _Backend(fails=RuntimeError("metal out of memory"))
    )

    with pytest.raises(RuntimeError):
        await recognizer.preload()
    readiness = await recognizer.readiness()

    assert readiness.state == "not_ready"
    assert "metal out of memory" in readiness.detail


@pytest.mark.asyncio
async def test_a_runtime_with_nothing_to_preload_reports_unknown():
    """`moshi_server` connects per session, so warm-up proves nothing about it.

    Answering "ready" here would be a health endpoint vouching for a remote
    server nobody has ever reached (L-27). It stays `unknown` until Slice 6B
    implements a real probe — which is the point: the gap is visible.
    """
    recognizer = KyutaiRecognizer(lambda: _Backend(warms=False))  # type: ignore[arg-type]

    await recognizer.preload()
    readiness = await recognizer.readiness()

    assert readiness.state == "unknown"
    assert "6B" in readiness.detail


def test_readiness_is_ready_only_for_the_ready_state():
    assert RecognizerReadiness(state="ready", detail="").ready
    assert not RecognizerReadiness(state="not_ready", detail="").ready
    assert not RecognizerReadiness(state="unknown", detail="").ready
