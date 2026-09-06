"""FastAPI dependencies: settings, session, principal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from mosaique.app.auth.tokens import Principal, verify_token
from mosaique.config.settings import Settings, get_settings
from mosaique.domain.errors import InvalidToken
from mosaique.persistence.engine import get_sessionmaker

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request; commit on success, roll back on failure."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_principal(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise InvalidToken("Missing bearer token")
    return verify_token(authorization.split(" ", 1)[1], secret=settings.token_secret)


PrincipalDep = Annotated[Principal, Depends(get_principal)]
