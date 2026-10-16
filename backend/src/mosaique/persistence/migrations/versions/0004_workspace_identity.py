"""Add global accounts/workspaces; never claim or backfill legacy users by email.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("issuer", "subject", name="uq_accounts_identity"),
    )
    op.create_table(
        "memberships",
        sa.Column("organization_id", sa.String(26), sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("account_id", sa.String(26), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(8), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member')", name="role_valid"),
    )
    op.create_table(
        "workspace_invitations",
        sa.ForeignKeyConstraint(
            ["organization_id", "invited_by"],
            ["memberships.organization_id", "memberships.account_id"],
            name="fk_workspace_invitations_inviter_membership",
        ),
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("organization_id", sa.String(26), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invited_by", sa.String(26), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_workspace_invitations_organization_id", "workspace_invitations", ["organization_id"])


def downgrade() -> None:
    raise RuntimeError("Additive identity migration: preserve data; roll back application code only")
