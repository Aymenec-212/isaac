"""Migration 2: transcript segment corrections (Slice 6R item 7, Q9).

Four nullable columns on `transcript_segments`. **Nothing is dropped, renamed or
rewritten**, and that is the whole design: Q9 answers "are transcript corrections
in scope?" with *yes, additive only*, so `text` and `words` keep holding exactly
what the ASR produced and a human edit lands beside them.

Why that constraint is load-bearing rather than fussy: L-28's shape, the 1.43%
WER measured on 2026-09-08 and every `[measure]` row in `PROJECT_STATE.md` §8 are
claims about what the *model* said. Let a correction overwrite `text` and all of
them become unfalsifiable after the fact, with no way to tell an edit from a
transcription. Additive storage makes that impossible by construction instead of
by remembering.

Nullable throughout, so this migration is a no-op for existing rows and needs no
backfill: a segment nobody has edited has four NULLs and reads exactly as before.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcript_segments",
        sa.Column("corrected_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "transcript_segments",
        sa.Column("corrected_participant_id", sa.String(length=26), nullable=True),
    )
    op.add_column(
        "transcript_segments",
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transcript_segments",
        sa.Column("corrected_by", sa.String(length=26), nullable=True),
    )
    # SET NULL rather than CASCADE on both: losing the participant a correction
    # reattributed to, or the user who made it, must not delete the corrected
    # text itself. The correction is the record; the references are provenance.
    op.create_foreign_key(
        "fk_segments_corrected_participant",
        "transcript_segments",
        "participants",
        ["corrected_participant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_segments_corrected_by",
        "transcript_segments",
        "users",
        ["corrected_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Dropping these loses every correction ever made. There is no way to
    # preserve them on the way down, because the raw columns are deliberately
    # not the place corrections live.
    op.drop_constraint("fk_segments_corrected_by", "transcript_segments", type_="foreignkey")
    op.drop_constraint(
        "fk_segments_corrected_participant", "transcript_segments", type_="foreignkey"
    )
    op.drop_column("transcript_segments", "corrected_by")
    op.drop_column("transcript_segments", "corrected_at")
    op.drop_column("transcript_segments", "corrected_participant_id")
    op.drop_column("transcript_segments", "corrected_text")
