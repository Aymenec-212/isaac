"""Typed configuration fails fast (engineering skill 20)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mosaique.config.settings import Settings

VALID = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "token_secret": "x" * 32,
}


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Settings read the environment, so a config test must control it fully."""
    import os

    for key in [k for k in os.environ if k.startswith("MOSAIQUE_")]:
        monkeypatch.delenv(key, raising=False)


def test_valid_settings_load():
    s = Settings(_env_file=None, **VALID)
    assert s.environment == "local"
    assert s.log_transcript_text is False


def test_missing_required_key_raises():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, token_secret="x" * 32)


def test_short_token_secret_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**VALID, "token_secret": "too-short"})


def test_non_asyncpg_driver_rejected():
    with pytest.raises(ValidationError, match="asyncpg"):
        Settings(_env_file=None, **{**VALID, "database_url": "postgresql://u:p@localhost:5432/db"})


def test_unknown_key_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **VALID, mystery_option=1)


def test_transcript_logging_refused_in_pilot():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **VALID, environment="pilot", log_transcript_text=True)


def test_sync_url_swaps_driver_for_alembic():
    assert Settings(_env_file=None, **VALID).sync_database_url.startswith("postgresql+psycopg://")
