"""comments and shared saved views

Revision ID: c4d81f2a9e63
Revises: a3c9e41d7b20
Create Date: 2026-11-04 10:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.adapters.db.types

revision: str = "c4d81f2a9e63"
down_revision: str | None = "a3c9e41d7b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=20), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("author", sa.String(length=100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", app.adapters.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.create_index(
            "ix_comments_resource", ["resource_type", "resource_id", "created_at"], unique=False
        )

    with op.batch_alter_table("saved_views", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    # verify-audit now compares audit_head.appends with the row count, but a3c9e41d7b20 seeded
    # it at 0 whatever was in the log, so count the rows written before the counter existed.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT COUNT(*) FROM audit_log")).scalar_one()
    updated = bind.execute(
        sa.text("UPDATE audit_head SET appends = :rows WHERE id = 1"), {"rows": rows}
    )
    if updated.rowcount == 0:
        bind.execute(
            sa.text("INSERT INTO audit_head (id, appends) VALUES (1, :rows)"), {"rows": rows}
        )


def downgrade() -> None:
    with op.batch_alter_table("saved_views", schema=None) as batch_op:
        batch_op.drop_column("shared")

    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.drop_index("ix_comments_resource")

    op.drop_table("comments")
