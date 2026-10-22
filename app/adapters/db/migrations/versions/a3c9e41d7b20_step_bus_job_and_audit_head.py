"""step bus job id and audit head lock row

Revision ID: a3c9e41d7b20
Revises: 7ffcb5d8ab0e
Create Date: 2026-10-22 18:10:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3c9e41d7b20"
down_revision: str | None = "7ffcb5d8ab0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("run_steps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bus_job_id", sa.Integer(), nullable=True))

    audit_head = op.create_table(
        "audit_head",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appends", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(audit_head, [{"id": 1, "appends": 0}])


def downgrade() -> None:
    op.drop_table("audit_head")
    with op.batch_alter_table("run_steps", schema=None) as batch_op:
        batch_op.drop_column("bus_job_id")
