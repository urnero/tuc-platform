"""Выгрузка заказов таблицей: одни и те же колонки для CSV админки (B09)
и Google-таблицы учёта (B11, `app/sheets.py`).

Одна строка — один заказ. Часы и граммы — на весь тираж (на штуку × qty),
даты — по Москве, оплата — дата успешного платежа ЮKassa (пусто, если платили не на сайте).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, Payment
from app.telegram import STATUS_LABELS

MSK = timedelta(hours=3)

# Имена колонок (первая строка CSV и таблицы). Порядок = порядок значений в order_row().
COLUMNS = [
    "id", "number", "created_msk", "status", "status_label", "customer_name", "phone",
    "email", "delivery", "address", "material", "supports", "qty", "postprocess", "total",
    "print_time_h", "material_g", "original_name", "comment", "paid_msk", "upload_id",
]


def fmt_dt(dt: datetime | None) -> str:
    """Дата из БД → «19.10.2026 23:41» по Москве. SQLite теряет пояс — считаем UTC."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (dt.astimezone(UTC) + MSK).strftime("%d.%m.%Y %H:%M")


def paid_at_by_order(db: Session, orders: list[Order]) -> dict[int, datetime]:
    """Когда прошла онлайн-оплата по каждому заказу (только успешные платежи)."""
    if not orders:
        return {}
    rows = db.execute(
        select(Payment.order_id, Payment.paid_at).where(
            Payment.order_id.in_([o.id for o in orders]), Payment.status == "succeeded"
        )
    )
    return {order_id: paid_at for order_id, paid_at in rows}


def order_row(o: Order, paid_at: datetime | None) -> list:
    """Заказ → список значений в порядке COLUMNS."""
    quote = o.quote or {}
    return [
        o.id, f"ТУЦ-{o.id}", fmt_dt(o.created_at), o.status, STATUS_LABELS[o.status],
        o.customer_name, o.phone, o.email or "", o.delivery, o.address or "",
        o.material, int(o.supports), o.qty, o.postprocess, o.total,
        round((quote.get("print_time_s") or 0) / 3600 * o.qty, 2),
        round((quote.get("material_g") or 0) * o.qty, 1),
        o.original_name or "", o.comment or "", fmt_dt(paid_at), o.upload_id,
    ]


def order_rows(db: Session, orders: list[Order]) -> list[list]:
    """Строки для всех заказов (без заголовка)."""
    paid = paid_at_by_order(db, orders)
    return [order_row(o, paid.get(o.id)) for o in orders]


def all_orders(db: Session) -> list[Order]:
    """Все заказы по номеру — так их удобно смотреть в таблице учёта."""
    return list(db.scalars(select(Order).order_by(Order.id)))
