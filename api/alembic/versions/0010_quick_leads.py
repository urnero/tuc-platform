"""Быстрые заявки (B52): «перезвоните мне» из выходного попапа и «нет файла — фото/описание».

В таблицу `leads` добавлены вид заявки `kind`, страница `page` и фото `photo`;
`upload_id` и `material` стали необязательными (у заявки без модели их нет).
Старые заявки получают kind = 'material'.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leads") as batch:  # batch — чтобы работало и на SQLite
        batch.add_column(
            sa.Column("kind", sa.String(16), nullable=False, server_default="material")
        )
        batch.add_column(sa.Column("page", sa.String(200), nullable=True))
        batch.add_column(sa.Column("photo", sa.String(64), nullable=True))
        batch.alter_column("upload_id", existing_type=sa.String(32), nullable=True)
        batch.alter_column("material", existing_type=sa.String(32), nullable=True)
    op.create_index("ix_leads_kind", "leads", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_leads_kind", table_name="leads")
    # Быстрые заявки без модели не влезут в старую схему (upload_id NOT NULL) — удаляем их.
    op.execute("DELETE FROM leads WHERE kind <> 'material'")
    with op.batch_alter_table("leads") as batch:
        batch.alter_column("material", existing_type=sa.String(32), nullable=False)
        batch.alter_column("upload_id", existing_type=sa.String(32), nullable=False)
        batch.drop_column("photo")
        batch.drop_column("page")
        batch.drop_column("kind")
