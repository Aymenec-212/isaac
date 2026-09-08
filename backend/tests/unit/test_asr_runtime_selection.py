"""Choosing an ASR runtime from configuration (ADR-13, fail-fast).

The important property is that nothing falls back silently. A misconfigured
runtime that quietly became the fake would put scripted French into a real
meeting's transcript, and the only thing downstream that could ever reveal it is
`Meeting.asr_version` — after the fact.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mosaique.asr_runtime import build_recognizer
from mosaique.config.settings import Settings
from mosaique.speech.adapters.fake import FakeRecognizer
from mosaique.speech.adapters.kyutai import KyutaiRecognizer
from mosaique.speech.interfaces import StreamingRecognizer

BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "token_secret": "x" * 32,
}


def settings(**overrides) -> Settings:
    return Settings(**{**BASE, **overrides})  # type: ignore[arg-type]


def test_the_default_runtime_is_the_fake():
    """A default that loaded two gigabytes of weights would be a poor one."""
    assert settings().asr_runtime == "fake"
    assert isinstance(build_recognizer(settings()), FakeRecognizer)


def test_an_unknown_runtime_is_refused_by_configuration():
    with pytest.raises(ValidationError):
        settings(asr_runtime="whisper")


def test_moshi_server_without_a_url_fails_at_startup_not_mid_meeting():
    with pytest.raises(ValidationError, match="asr_moshi_server_url"):
        settings(asr_runtime="moshi_server")


def test_the_moshi_server_runtime_builds_a_kyutai_recognizer():
    recognizer = build_recognizer(
        settings(asr_runtime="moshi_server", asr_moshi_server_url="ws://gpu.internal:8080")
    )

    assert isinstance(recognizer, KyutaiRecognizer)
    assert isinstance(recognizer, StreamingRecognizer)


def test_every_runtime_satisfies_the_one_protocol_the_app_knows_about():
    """The seam, stated as an assertion: the app never learns which is which."""
    for recognizer in (
        build_recognizer(settings()),
        build_recognizer(
            settings(asr_runtime="moshi_server", asr_moshi_server_url="ws://gpu:8080")
        ),
    ):
        assert isinstance(recognizer, StreamingRecognizer)
