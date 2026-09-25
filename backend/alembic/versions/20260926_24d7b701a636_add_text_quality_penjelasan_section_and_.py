"""add text quality, penjelasan, section and version key

Revision ID: 24d7b701a636
Revises: 798927a72b33
Create Date: 2026-09-26 00:56:20.393088

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "24d7b701a636"
down_revision: str | Sequence[str] | None = "798927a72b33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("provisions", sa.Column("section", sa.Text(), nullable=True))
    op.add_column("provisions", sa.Column("penjelasan", sa.Text(), nullable=True))
    # NULLS NOT DISTINCT requires PostgreSQL 15+.
    op.create_unique_constraint(
        "uq_provisions_version",
        "provisions",
        ["regulation_id", "article", "amended_by_id", "amendment_ref"],
        postgresql_nulls_not_distinct=True,
    )
    # No default on purpose; the table holds no rows before the first ingestion.load.
    op.add_column("regulations", sa.Column("text_quality", sa.Text(), nullable=False))
    # Autogenerate does not detect CHECK constraints.
    op.create_check_constraint(
        op.f("ck_regulations_text_quality"),
        "regulations",
        "text_quality IN ('native', 'ocr', 'manual')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_regulations_text_quality"), "regulations", type_="check")
    op.drop_column("regulations", "text_quality")
    op.drop_constraint("uq_provisions_version", "provisions", type_="unique")
    op.drop_column("provisions", "penjelasan")
    op.drop_column("provisions", "section")
