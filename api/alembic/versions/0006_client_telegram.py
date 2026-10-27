"""Статусы клиенту (B34): chat_id клиента в Telegram у заказа.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Пусто у всех старых заказов: клиент подключает Telegram сам со страницы заказа.
    with op.batch_alter_table("orders") as batch:  # batch — чтобы работало и на SQLite
        batch.add_column(sa.Column("telegram_chat_id", sa.String(32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("telegram_chat_id")
