"""Typed application settings.

Configuration is validated once at import of `get_settings()` and the process
fails fast when anything required is missing (engineering skill 20).
Nothing in the codebase reads `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every knob the app-server has. Extra keys are rejected, not ignored."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MOSAIQUE_",
        extra="forbid",
    )

    environment: Literal["local", "ci", "pilot"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: PostgresDsn = Field(
        description="PostgreSQL DSN. asyncpg driver is enforced by the validator.",
    )

    # Signing key for host and session tokens (tech spec 13.1).
    token_secret: str = Field(min_length=32)
    host_token_ttl_hours: int = Field(default=12, ge=1, le=168)

    # Prototype tenancy: one seeded organization (tech spec 4, ADR-08).
    seed_organization_name: str = "Mosaique Pilot"
    seed_host_email: str = "pilot@mosaique.local"
    seed_host_display_name: str = "Pilote"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Raw per-participant PCM (ADR-06). Retention policy is still open (Q3).
    audio_root: Path = Path("audio")

    # --- ASR runtime (ADR-13) --------------------------------------------
    # The model is fixed; the runtime is a configuration axis. `fake` is the
    # default because every test and every slice before this one runs on it,
    # and because a default that silently tries to load two gigabytes of
    # weights would be a poor one.
    asr_runtime: Literal["fake", "mlx", "moshi_server"] = "fake"
    asr_model_repo: str = "kyutai/stt-1b-en_fr-mlx"
    asr_moshi_server_url: str | None = None
    asr_moshi_server_api_key: str | None = None
    # The server does not report what it loaded, so whoever runs it says here.
    # A wrong value produces a wrong `Meeting.asr_version` (ADR-13 §3).
    asr_moshi_server_quantization: str = "bf16"

    # Refused in production config (tech spec 13.3).
    log_transcript_text: bool = False

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, v: PostgresDsn) -> PostgresDsn:
        if v.scheme != "postgresql+asyncpg":
            raise ValueError(
                f"database_url must use the postgresql+asyncpg scheme; got {v.scheme!r}"
            )
        return v

    @field_validator("asr_moshi_server_url")
    @classmethod
    def _moshi_server_needs_a_url(cls, v: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        """Fail at startup, not at the first participant's first frame.

        ADR-13 asks for fail-fast on an unavailable runtime. A missing URL is
        the one unavailability that can be seen before any audio arrives, so it
        is caught here rather than surfacing as a dead stream mid-meeting.
        """
        if info.data.get("asr_runtime") == "moshi_server" and not v:
            raise ValueError("asr_moshi_server_url is required when asr_runtime is 'moshi_server'")
        return v

    @field_validator("log_transcript_text")
    @classmethod
    def _no_transcript_logging_in_pilot(cls, v: bool, info) -> bool:  # type: ignore[no-untyped-def]
        if v and info.data.get("environment") == "pilot":
            raise ValueError("log_transcript_text must be false in the pilot environment")
        return v

    @property
    def sync_database_url(self) -> str:
        """Alembic runs synchronously; swap the driver for migrations only."""
        return str(self.database_url).replace("postgresql+asyncpg", "postgresql+psycopg")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings. Raises at startup when configuration is invalid."""
    return Settings()  # type: ignore[call-arg]
