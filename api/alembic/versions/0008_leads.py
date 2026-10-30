"""Заявки «цена по запросу» (B44) — своя таблица `leads`, контакты убраны из `events`.

Раньше имя, телефон, e-mail и комментарий клиента лежали в `events.props` заявки
`material_request`. В `events` данных клиента быть не должно (их не обезличивает
app/anonymize.py, их видит read-only пользователь аналитики). Миграция переносит старые
заявки в `leads` и оставляет в событии только material, qty и lead_id.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

CONTACT_KEYS = ("name", "phone", "email", "comment")


def upgrade() -> None:
    leads = op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("upload_id", sa.String(32), nullable=False),
        sa.Column("material", sa.String(32), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("telegram_sent", sa.Boolean(), nullable=False),
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_leads_created_at", "leads", ["created_at"])
    op.create_index("ix_leads_upload_id", "leads", ["upload_id"])

    # Перенос старых заявок. Заявок единицы — читаем в Python, так одинаково на Postgres и SQLite.
    events = sa.table(
        "events",
        sa.column("id", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("name", sa.String),
        sa.column("upload_id", sa.String),
        sa.column("props", sa.JSON),
    )
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(events.c.id, events.c.created_at, events.c.upload_id, events.c.props).where(
            events.c.name == "material_request"
        )
    ).all()
    for ev_id, created_at, upload_id, props in rows:
        props = dict(props or {})
        if not any(k in props for k in CONTACT_KEYS):
            continue
        lead_id = conn.execute(
            sa.insert(leads)
            .values(
                created_at=created_at,
                upload_id=upload_id or "",
                material=str(props.get("material") or ""),
                qty=int(props.get("qty") or 1),
                name=str(props.get("name") or ""),
                phone=str(props.get("phone") or ""),
                email=props.get("email"),
                comment=props.get("comment"),
                # Тогда флаг не сохраняли — считаем «не ушла», владелец увидит в админке.
                telegram_sent=False,
            )
            .returning(leads.c.id)
        ).scalar_one()
        clean = {k: v for k, v in props.items() if k not in CONTACT_KEYS}
        clean["lead_id"] = lead_id
        conn.execute(sa.update(events).where(events.c.id == ev_id).values(props=clean))


def downgrade() -> None:
    # Контакты обратно в events не возвращаем — это и была ошибка.
    op.drop_index("ix_leads_upload_id", table_name="leads")
    op.drop_index("ix_leads_created_at", table_name="leads")
    op.drop_table("leads")
