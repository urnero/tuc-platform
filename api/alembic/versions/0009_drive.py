"""Google Drive (B46): ссылка на папку заказа с его файлами.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Пусто у старых заказов: ночная задача worker (drive_backfill) докопирует свежие сама.
    with op.batch_alter_table("orders") as batch:  # batch — чтобы работало и на SQLite
        batch.add_column(sa.Column("drive_folder_url", sa.String(500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("drive_folder_url")
