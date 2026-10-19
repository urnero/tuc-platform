"""Таблица заказов (B06).

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # клиент
        sa.Column("customer_name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("delivery", sa.String(32), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        # что печатаем
        sa.Column("upload_id", sa.String(32), nullable=False),
        sa.Column("quote_id", sa.String(64), nullable=False),
        sa.Column("original_name", sa.String(200), nullable=True),
        sa.Column("material", sa.String(20), nullable=False),
        sa.Column("supports", sa.Boolean(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("postprocess", sa.String(32), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("quote", sa.JSON(), nullable=False),
    )
    op.create_index("ix_orders_token", "orders", ["token"], unique=True)
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_upload_id", "orders", ["upload_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_upload_id", table_name="orders")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_token", table_name="orders")
    op.drop_table("orders")
