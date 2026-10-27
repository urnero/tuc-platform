"""Обезличивание заказов (B35): когда из заказа убрали данные клиента.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL — заказ ещё с данными клиента. Дату ставит ночной cron (app/anonymize.py)
    # через 5 лет после закрытия заказа, одновременно стирая имя, телефон, e-mail, адрес.
    with op.batch_alter_table("orders") as batch:  # batch — чтобы работало и на SQLite
        batch.add_column(sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("anonymized_at")
