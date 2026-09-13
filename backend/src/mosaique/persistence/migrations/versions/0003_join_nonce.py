"""Retry-safe meeting-scoped participant joins.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("join_nonce_hash", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_participants_join_nonce", "participants", ["meeting_id", "join_nonce_hash"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_participants_join_nonce", "participants", type_="unique")
    op.drop_column("participants", "join_nonce_hash")
