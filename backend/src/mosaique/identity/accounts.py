"""Global identity mapping and editable application profile, independent of OIDC SDKs."""

import hashlib

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mosaique.domain.errors import ErrorCode, InvalidToken, MosaiqueError
from mosaique.domain.ids import new_id
from mosaique.persistence.models.identity import Account


def identity_key(issuer: str, subject: str) -> str:
    return hashlib.sha256((issuer + "\0" + subject).encode()).hexdigest()


def lock_identity(db: Session, issuer: str, subject: str) -> None:
    """Serialize login and logout before an account row exists. Hash collisions only serialize."""
    key = int.from_bytes(bytes.fromhex(identity_key(issuer, subject))[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def resolve_account(
    db: Session, *, issuer: str, subject: str, email: str, email_verified: bool, initial_name: str
) -> str:
    """Called only after OIDC validation. Email never claims another account or history."""
    lock_identity(db, issuer, subject)
    statement = (
        insert(Account)
        .values(
            id=new_id(),
            issuer=issuer,
            subject=subject,
            email=email,
            email_verified=email_verified,
            display_name=initial_name[:120],
            disabled=False,
        )
        .on_conflict_do_update(
            constraint="uq_accounts_identity",
            set_={
                "email": email,
                "email_verified": email_verified,
            },
        )
        .returning(Account.id)
    )
    account_id = db.execute(statement).scalar_one()
    account = db.get(Account, account_id, populate_existing=True)
    if account is None or account.disabled:
        raise InvalidToken()
    return account_id


def update_profile(db: Session, account_id: str, name: str) -> str:
    account = db.get(Account, account_id, populate_existing=True)
    if account is None or account.disabled:
        raise InvalidToken()
    name = name.strip()
    if not name or len(name) > 120:
        raise MosaiqueError(ErrorCode.VALIDATION_FAILED, "Display name required (max 120)")
    account.display_name = name
    db.flush()
    return name
