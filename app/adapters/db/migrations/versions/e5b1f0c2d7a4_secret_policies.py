"""secret policies (ADR 0001) and the secrets on promotion requests

Revision ID: e5b1f0c2d7a4
Revises: c4d81f2a9e63
Create Date: 2026-11-12 15:00:00.000000

Existing secrets get empty lists, which refuse every use until an Admin sets the policy: nothing
stays silently open after the upgrade (ADR 0001, "Consequences").
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5b1f0c2d7a4"
down_revision: str | None = "c4d81f2a9e63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("secrets_metadata", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("allowed_hosts", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.add_column(
            sa.Column("environments", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
    with op.batch_alter_table("promotions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("secrets", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("promotions", schema=None) as batch_op:
        batch_op.drop_column("secrets")
    with op.batch_alter_table("secrets_metadata", schema=None) as batch_op:
        batch_op.drop_column("environments")
        batch_op.drop_column("allowed_hosts")
