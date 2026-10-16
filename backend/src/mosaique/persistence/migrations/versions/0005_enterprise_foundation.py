"""Enterprise sessions and explicit meeting authority, preserving legacy history.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_provider_sessions",
        sa.Column("identity_hash", sa.String(64), primary_key=True),
        sa.Column("sid_hash", sa.String(64), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "workspace_audit",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "organization_id", sa.String(26), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("actor_id", sa.String(26), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(26), nullable=False),
        sa.Column("context_id", sa.String(26), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_workspace_audit_organization_id", "workspace_audit", ["organization_id"])
    op.create_table(
        "login_attempts",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("verifier", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempts_browser_hash", "login_attempts", ["browser_hash"])
    op.add_column(
        "accounts", sa.Column("display_name", sa.String(120), server_default="", nullable=False)
    )
    op.add_column(
        "meetings", sa.Column("mode", sa.String(16), server_default="legacy", nullable=False)
    )
    op.add_column("meetings", sa.Column("organizer_account_id", sa.String(26), nullable=True))
    op.alter_column("meetings", "host_user_id", existing_type=sa.String(26), nullable=True)
    op.create_unique_constraint("uq_meetings_org_id", "meetings", ["organization_id", "id"])
    op.create_foreign_key(
        "fk_meetings_organizer_membership",
        "meetings",
        "memberships",
        ["organization_id", "organizer_account_id"],
        ["organization_id", "account_id"],
    )
    op.create_check_constraint("mode_valid", "meetings", "mode IN ('legacy', 'enterprise')")
    op.create_check_constraint(
        "identity_mode_valid",
        "meetings",
        "(mode = 'legacy' AND host_user_id IS NOT NULL AND organizer_account_id IS NULL) OR "
        "(mode = 'enterprise' AND organizer_account_id IS NOT NULL AND host_user_id IS NULL)",
    )
    op.create_table(
        "meeting_access",
        sa.Column("organization_id", sa.String(26), primary_key=True),
        sa.Column("meeting_id", sa.String(26), primary_key=True),
        sa.Column("account_id", sa.String(26), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "meeting_id"],
            ["meetings.organization_id", "meetings.id"],
            name="fk_meeting_access_meeting",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["memberships.organization_id", "memberships.account_id"],
            name="fk_meeting_access_membership",
        ),
    )
    op.create_table(
        "account_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(26),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_sid_hash", sa.String(64), nullable=True),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_sessions_account_id", "account_sessions", ["account_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Additive foundation migration: preserve data; roll back application code only"
    )
