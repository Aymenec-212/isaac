"""Durable browser/account login boundaries and organizer revocation.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sa.Sequence("identity_login_generation").create(op.get_bind())
    op.create_table(
        "browser_logins",
        sa.Column("browser_hash", sa.String(64), primary_key=True),
        sa.Column("generation", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "accounts",
        sa.Column("login_generation", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column("account_sessions", sa.Column("browser_hash", sa.String(64), nullable=True))
    op.create_foreign_key(
        "fk_account_sessions_browser_hash_browser_logins",
        "account_sessions",
        "browser_logins",
        ["browser_hash"],
        ["browser_hash"],
    )
    op.add_column(
        "account_sessions", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "login_attempts",
        sa.Column("browser_generation", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "login_attempts",
        sa.Column("login_generation", sa.BigInteger(), server_default="0", nullable=False),
    )
    # Existing pending attempts cannot cross the new cancellation boundary. Keep
    # their rows for expiry/cleanup, but make their saved generation obsolete.
    op.execute(
        "INSERT INTO browser_logins(browser_hash, generation) SELECT DISTINCT browser_hash, 1 FROM login_attempts"
    )
    op.add_column(
        "meetings", sa.Column("organizer_revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    # An already-revoked organizer must not regain authority merely by upgrading.
    op.execute(
        "UPDATE meetings m SET organizer_revoked_at = s.revoked_at FROM memberships s "
        "WHERE m.mode = 'enterprise' AND m.organization_id = s.organization_id "
        "AND m.organizer_account_id = s.account_id AND s.revoked_at IS NOT NULL"
    )

    # Re-invitation clears Membership.revoked_at. The existing audit ledger still
    # proves earlier revocations; only meetings predating that revocation qualify.
    op.execute(
        "UPDATE meetings m SET organizer_revoked_at = r.revoked_at FROM "
        "(SELECT organization_id, target_id, max(created_at) AS revoked_at "
        "FROM workspace_audit WHERE action = 'membership.revoked' "
        "GROUP BY organization_id, target_id) r "
        "WHERE m.mode = 'enterprise' AND m.organization_id = r.organization_id "
        "AND m.organizer_account_id = r.target_id AND m.created_at <= r.revoked_at "
        "AND m.organizer_revoked_at IS NULL"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve revocation boundaries; no destructive authorization downgrade")
