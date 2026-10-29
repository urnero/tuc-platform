"""Обезличивание старых заказов по политике ПДн (B35, /policy, раздел 6).

Что обещано клиенту: данные заказов и оплат хранятся 5 лет после выполнения заказа
(срок хранения документов об оплате по закону), затем удаляются или обезличиваются.

Что делаем: заказ со статусом «выдан» или «отменён», закрытый больше
ANONYMIZE_ORDERS_DAYS назад (по `orders.updated_at`), теряет всё, по чему можно узнать
клиента — имя, телефон, e-mail, адрес, комментарий, реквизиты организации (B33),
chat_id в Telegram (B34). В `orders.anonymized_at` пишется дата. Сам заказ остаётся:
номер, статус, даты, сумма, материал, тираж, снимок расчёта — всё, что нужно аналитике
(docs/ANALYTICS.md) и учёту. У оплат (`payments`) стирается сырой ответ ЮKassa (`raw`) —
там могут быть данные карты и чека; сумма, статус и id платежа остаются.

Заявки «цена по запросу» (`leads`, B44) живут столько же, считая от даты заявки: у них
стираются имя, телефон, e-mail и комментарий; материал, тираж и дата остаются.

Файлы модели к этому времени давно удалены (app/cleanup.py — через год после закрытия).
Таблицу `events` не трогаем: в ней нет данных клиента, только id загрузок, заказов и заявок.

Запуск: cron в worker каждую ночь (app/worker.py) и руками —
`python -m app.anonymize` (посмотреть, что изменится: `python -m app.anonymize --dry-run`).
ANONYMIZE_ORDERS_DAYS=0 выключает обезличивание.
"""

import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.cleanup import CLOSED_STATUSES
from app.config import settings
from app.db import session_factory
from app.models import Lead, Order, Payment

log = logging.getLogger(__name__)

# Чем заменяем. Имя и телефон в БД обязательные (NOT NULL) — туда пустая строка,
# остальные поля могут быть NULL — туда NULL.
BLANK_ORDER_FIELDS: dict = {
    "customer_name": "",
    "phone": "",
    "email": None,
    "address": None,
    "comment": None,
    "company_name": None,
    "company_inn": None,
    "company_kpp": None,
    "company_address": None,
    "telegram_chat_id": None,
}
BLANK_LEAD_FIELDS: dict = {"name": "", "phone": "", "email": None, "comment": None}


@dataclass
class AnonymizeReport:
    orders: list[int] = field(default_factory=list)  # номера обезличенных заказов
    payments: int = 0  # у скольких оплат стёрт raw
    leads: list[int] = field(default_factory=list)  # номера обезличенных заявок (B44)
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "orders": len(self.orders),
            "payments": self.payments,
            "leads": len(self.leads),
            "dry_run": self.dry_run,
        }


def _as_utc(dt: datetime) -> datetime:
    """SQLite отдаёт время без зоны — считаем, что это UTC (так его и пишет utcnow())."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def find_orders(db: Session, now: datetime | None = None) -> list[int]:
    """Номера заказов, которым пора обезличиться. Ничего не меняет."""
    if settings.anonymize_orders_days <= 0:
        return []
    now = now or datetime.now(UTC)
    deadline = now - timedelta(days=settings.anonymize_orders_days)
    rows = db.execute(
        select(Order.id, Order.updated_at)
        .where(Order.status.in_(CLOSED_STATUSES), Order.anonymized_at.is_(None))
        .order_by(Order.id)
    ).all()
    # Сравниваем в Python, а не в SQL: SQLite хранит даты строкой, и сравнение с зоной
    # и без зоны там ненадёжно; заказов за 5 лет немного, это не тяжело.
    return [order_id for order_id, updated_at in rows if _as_utc(updated_at) <= deadline]


def find_leads(db: Session, now: datetime | None = None) -> list[int]:
    """Номера заявок «цена по запросу», которым пора обезличиться (срок — от даты заявки)."""
    if settings.anonymize_orders_days <= 0:
        return []
    now = now or datetime.now(UTC)
    deadline = now - timedelta(days=settings.anonymize_orders_days)
    rows = db.execute(
        select(Lead.id, Lead.created_at).where(Lead.anonymized_at.is_(None)).order_by(Lead.id)
    ).all()
    return [lead_id for lead_id, created_at in rows if _as_utc(created_at) <= deadline]


def anonymize_orders(
    db: Session, now: datetime | None = None, dry_run: bool = False
) -> AnonymizeReport:
    """Обезличить всё, чей срок вышел. dry_run=True — только перечислить."""
    now = now or datetime.now(UTC)
    report = AnonymizeReport(
        orders=find_orders(db, now), leads=find_leads(db, now), dry_run=dry_run
    )
    if report.leads and not dry_run:
        db.execute(
            update(Lead)
            .where(Lead.id.in_(report.leads))
            .values(**BLANK_LEAD_FIELDS, anonymized_at=now)
        )
        db.commit()
    if report.leads:
        log.info(
            "Обезличивание: заявок «цена по запросу» %s — %d",
            "обезличил бы" if dry_run else "обезличено",
            len(report.leads),
        )
    if not report.orders:
        log.info("Обезличивание: заказов старше %d дн. нет", settings.anonymize_orders_days)
        return report

    ids = report.orders
    report.payments = _count_payments_with_raw(db, ids)
    if not dry_run:
        # Core-UPDATE, а не правка объектов: так `updated_at` не сдвигается (onupdate
        # срабатывает только когда колонки нет в SET), и дата закрытия заказа остаётся честной.
        db.execute(
            update(Order)
            .where(Order.id.in_(ids))
            .values(**BLANK_ORDER_FIELDS, anonymized_at=now, updated_at=Order.updated_at)
        )
        db.execute(
            update(Payment)
            .where(Payment.order_id.in_(ids))
            .values(raw={}, updated_at=Payment.updated_at)
        )
        db.commit()
    log.info(
        "Обезличивание: %s %d заказов (№ %s), оплат с сырым ответом ЮKassa — %d%s",
        "обезличил бы" if dry_run else "обезличено",
        len(ids),
        ", ".join(str(i) for i in ids[:20]) + ("…" if len(ids) > 20 else ""),
        report.payments,
        " (пробный прогон)" if dry_run else "",
    )
    return report


def _count_payments_with_raw(db: Session, order_ids: list[int]) -> int:
    rows = db.execute(select(Payment.raw).where(Payment.order_id.in_(order_ids))).all()
    return sum(1 for (raw,) in rows if raw)


def anonymize_job(dry_run: bool = False) -> dict:
    """Для cron в worker и CLI: своя сессия БД."""
    with session_factory()() as db:
        return anonymize_orders(db, dry_run=dry_run).to_dict()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in args
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = anonymize_job(dry_run=dry_run)
    verb = "обезличилось бы" if dry_run else "обезличено"
    print(
        f"Заказов {verb}: {result['orders']} (закрыты больше "
        f"{settings.anonymize_orders_days} дн. назад), оплат с очищенным ответом ЮKassa: "
        f"{result['payments']}, заявок «цена по запросу»: {result['leads']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
