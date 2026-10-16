"""Local/CI browser fixture only. No HTTP bypass; requires a disposable *_test DB.

Outputs test session credentials to stdout for Playwright's private fixture file.
Never run against an operational database.
"""

import asyncio
import json

from mosaique.config.settings import get_settings
from mosaique.domain.ids import new_id
from mosaique.identity.sessions import Sessions
from mosaique.persistence.engine import dispose_engine, get_sessionmaker, init_engine
from mosaique.persistence.models.identity import Account


async def main() -> None:
    settings = get_settings()
    if settings.environment != "ci" or not settings.database_url.path.endswith("_test"):
        raise RuntimeError("Browser fixtures require ci and a disposable *_test database")
    init_engine(settings)
    try:
        result = {}
        async with get_sessionmaker()() as db:
            for label in ("owner", "member"):
                account = Account(
                    id=new_id(),
                    issuer="https://browser.test/",
                    subject=new_id(),
                    email=f"{label}-{new_id()}@browser.test",
                    email_verified=True,
                    display_name=label.title(),
                )
                db.add(account)
                await db.flush()
                token = await db.run_sync(
                    lambda s, account_id=account.id: Sessions(s).issue(account_id)
                )
                result[label] = {"id": account.id, "email": account.email, "token": token}
            await db.commit()
        print(json.dumps(result))
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
