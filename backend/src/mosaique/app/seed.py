"""Seed the pilot organization and host account (Slice 0).

Idempotent: running it twice leaves one organization and one user.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from mosaique.app.auth.tokens import issue_host_token
from mosaique.config.settings import get_settings
from mosaique.domain.ids import new_id
from mosaique.persistence.engine import dispose_engine, init_engine, session_scope
from mosaique.persistence.models import Organization, User


async def seed() -> tuple[str, str, str]:
    """Return (organization_id, user_id, host_token)."""
    settings = get_settings()
    async with session_scope() as session:
        org = (
            await session.execute(
                select(Organization).where(Organization.name == settings.seed_organization_name)
            )
        ).scalar_one_or_none()
        if org is None:
            org = Organization(id=new_id(), name=settings.seed_organization_name)
            session.add(org)
            await session.flush()

        user = (
            await session.execute(
                select(User).where(
                    User.organization_id == org.id, User.email == settings.seed_host_email
                )
            )
        ).scalar_one_or_none()
        if user is None:
            user = User(
                id=new_id(),
                organization_id=org.id,
                email=settings.seed_host_email,
                display_name=settings.seed_host_display_name,
            )
            session.add(user)
            await session.flush()

        token = issue_host_token(
            user_id=user.id,
            organization_id=org.id,
            secret=settings.token_secret,
            ttl_hours=settings.host_token_ttl_hours,
        )
        return org.id, user.id, token


async def _main() -> None:
    init_engine(get_settings())
    try:
        org_id, user_id, token = await seed()
    finally:
        await dispose_engine()
    print(f"organization_id: {org_id}")
    print(f"user_id:         {user_id}")
    print(f"host_token:      {token}")


if __name__ == "__main__":
    asyncio.run(_main())
