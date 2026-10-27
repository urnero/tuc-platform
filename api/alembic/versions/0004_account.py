"""Кабинет клиента (B32): коды для входа и сессии.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_login_codes_email", "login_codes", ["email"])

    op.create_table(
        "client_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_client_sessions_token", "client_sessions", ["token"], unique=True)
    op.create_index("ix_client_sessions_email", "client_sessions", ["email"])


def downgrade() -> None:
    op.drop_index("ix_client_sessions_email", table_name="client_sessions")
    op.drop_index("ix_client_sessions_token", table_name="client_sessions")
    op.drop_table("client_sessions")
    op.drop_index("ix_login_codes_email", table_name="login_codes")
    op.drop_table("login_codes")
