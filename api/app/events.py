"""События воронки (B12): upload → quote → order → payment_started → paid.

Сервер пишет строку в таблицу `events` в тот момент, когда шаг случился
(загрузка принята, цена посчитана, заказ создан, платёж создан, оплата прошла).
Клиентской аналитики (JS, cookies) здесь нет: считаем то, что реально произошло на сервере.

Главное правило: аналитика никогда не ломает основной сценарий. `track()` ловит любые
ошибки БД, пишет их в лог и возвращает None — загрузка или заказ при этом проходят как обычно.

Как считать воронку (SQL, Superset) — docs/ANALYTICS.md. Сводка за 30 дней есть в админке
(/admin/orders, строка «Воронка»): `funnel()` ниже.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import session_factory
from app.models import EVENT_NAMES, Event

log = logging.getLogger(__name__)

# Чем считается «один» на каждом шаге воронки: до заказа — загрузка (upload_id),
# дальше — заказ (order_id). Так повторные расчёты по одной модели не раздувают шаг quote.
FUNNEL_KEY = {
    "upload": Event.upload_id,
    "quote": Event.upload_id,
    "order": Event.upload_id,
    "payment_started": Event.order_id,
    "paid": Event.order_id,
}


def track(
    name: str,
    *,
    upload_id: str | None = None,
    quote_id: str | None = None,
    order_id: int | None = None,
    props: dict | None = None,
    db: Session | None = None,
) -> Event | None:
    """Записать событие. Возвращает строку или None, если записать не удалось.

    С `db` — событие добавляется в сессию вызывающего кода и уедет в БД его же commit'ом
    (заказ и его событие `order` — одной транзакцией). Без `db` — своя короткая сессия:
    так пишут загрузки и расчёты, у которых сессии БД нет (они живут файлами в DATA_DIR).
    """
    if name not in EVENT_NAMES:
        raise ValueError(f"Неизвестное событие «{name}». Есть: {', '.join(EVENT_NAMES)}.")
    event = Event(
        name=name,
        upload_id=upload_id,
        quote_id=quote_id,
        order_id=order_id,
        props=props or {},
    )
    try:
        if db is not None:
            db.add(event)
            db.flush()
            return event
        with session_factory()() as own:
            own.add(event)
            own.commit()
            return event
    except Exception as e:  # noqa: BLE001 — любая ошибка БД: лог, но не 500 клиенту
        log.warning("Событие %s не записано: %s", name, e)
        return None


def funnel(db: Session, days: int = 30) -> dict[str, int]:
    """Сколько уникальных загрузок/заказов дошло до каждого шага за последние `days` дней.

    Пример ответа: {"upload": 40, "quote": 25, "order": 6, "payment_started": 5, "paid": 4}.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    counts = {name: 0 for name in EVENT_NAMES}
    rows = db.execute(
        select(Event.name, func.count(func.distinct(FUNNEL_KEY["upload"])))
        .where(Event.created_at >= since, Event.name.in_(("upload", "quote", "order")))
        .group_by(Event.name)
    ).all()
    counts.update(dict(rows))
    rows = db.execute(
        select(Event.name, func.count(func.distinct(FUNNEL_KEY["paid"])))
        .where(Event.created_at >= since, Event.name.in_(("payment_started", "paid")))
        .group_by(Event.name)
    ).all()
    counts.update(dict(rows))
    return counts
