"""B2B (B33): реквизиты юрлица и способ оплаты у заказа.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Старые заказы — от частных лиц, они платили онлайн: company_* пустые, payment_method = online.
    with op.batch_alter_table("orders") as batch:  # batch — чтобы работало и на SQLite
        batch.add_column(sa.Column("company_name", sa.String(300), nullable=True))
        batch.add_column(sa.Column("company_inn", sa.String(12), nullable=True))
        batch.add_column(sa.Column("company_kpp", sa.String(9), nullable=True))
        batch.add_column(sa.Column("company_address", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "payment_method", sa.String(16), nullable=False, server_default="online"
            )
        )
    # server_default нужен только чтобы заполнить существующие строки; дальше значение ставит код.
    with op.batch_alter_table("orders") as batch:
        batch.alter_column("payment_method", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("payment_method")
        batch.drop_column("company_address")
        batch.drop_column("company_kpp")
        batch.drop_column("company_inn")
        batch.drop_column("company_name")
