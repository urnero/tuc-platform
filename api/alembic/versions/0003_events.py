"""Таблица событий воронки (B12).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("upload_id", sa.String(32), nullable=True),
        sa.Column("quote_id", sa.String(64), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("props", sa.JSON(), nullable=False),
    )
    op.create_index("ix_events_created_at", "events", ["created_at"])
    op.create_index("ix_events_name", "events", ["name"])
    op.create_index("ix_events_upload_id", "events", ["upload_id"])
    op.create_index("ix_events_order_id", "events", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_events_order_id", table_name="events")
    op.drop_index("ix_events_upload_id", table_name="events")
    op.drop_index("ix_events_name", table_name="events")
    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_table("events")
