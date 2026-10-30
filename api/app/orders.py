"""Заказы (B06).

POST /api/v1/orders            — оформить заказ по расчёту цены: {quote_id, name, phone,
                                  email?, address?, comment?, consent, company?}. Доставка —
                                  из расчёта; если курьер — адрес обязателен. Ответ: заказ с token.
                                  `company` {name, inn, kpp?, address?} — заказ от организации
                                  или ИП (B33, `app/b2b.py`): e-mail обязателен (туда уйдут
                                  документы), `payment_method = invoice` — оплата по счёту.
GET  /api/v1/orders/{token}    — заказ для страницы статуса /order/<token>. Ссылку знает
                                  только клиент (token случайный), вход не нужен.
Кабинет клиента (B32, `app/account.py`) находит заказы по `email`: если клиент вошёл в кабинет
и не заполнил e-mail в форме, подставляем адрес из его сессии — заказ не потеряется из истории.

Заказ — строка в таблице `orders` (app/models.py). Цена фиксируется снимком расчёта.
Расчёт годится один раз и не дольше QUOTE_TTL_HOURS (24 ч): по просроченному — 410,
по уже заказанному — 409, в обоих случаях клиенту нужно пересчитать цену (цены могли измениться).
После создания заказа владельцу уходит сообщение в Telegram (B07, `app/telegram.py`) —
в фоне, после ответа клиенту, чтобы сбой Telegram не ломал оформление.
Оплата (B08) — `app/payments.py`: в ответе заказа есть блок `payment`
(включена ли онлайн-оплата, статус платежа, ссылка на форму ЮKassa).

Смена статуса — `change_status()`: её зовёт бот (B07), ЮKassa (B08, ставит paid),
админка (B09, `app/admin.py`). После смены клиенту уходит письмо и/или сообщение в Telegram
(B34, `app/notify.py`); при создании заказа — письмо «принят». В ответе заказа блок
`notifications`: куда приходят статусы и ссылка на бота для подключения Telegram.
"""

import re
import secrets
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import notify
from app import telegram as tg
from app.b2b import Company
from app.config import settings
from app.db import get_db
from app.events import track
from app.limits import orders_guard
from app.models import ORDER_STATUSES, Order, Payment
from app.quotes import load_quote, quote_expired_detail, quote_is_expired
from app.telegram import ACTIVE_STATUSES, STATUS_LABELS, notify_owner_new_order

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])
Db = Annotated[Session, Depends(get_db)]  # сессия БД на запрос

TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PhoneError(ValueError):
    pass


def order_number(order_id: int) -> str:
    """Номер заказа для людей: «BP-12». Префикс — настройка ORDER_NUMBER_PREFIX."""
    return f"{settings.order_number_prefix}-{order_id}"


def parse_order_number(raw: str) -> int | None:
    """«12», «BP-12», «bp 12», «№12», старый «ТУЦ-12» → 12; иначе None."""
    text = (raw or "").strip().lower()
    prefixes = {settings.order_number_prefix.lower(), "bp", "бп", "туц", "tuc"}
    m = re.fullmatch(r"([a-zа-яё]*)[-\s№#]*(\d+)", text)
    if not m or (m.group(1) and m.group(1) not in prefixes):
        return None
    return int(m.group(2))


def normalize_phone(raw: str) -> str:
    """«8 (999) 123-45-67», «+7 999 1234567», «9991234567» → «+79991234567».

    Иностранный номер с «+» и 10–15 цифрами оставляем как есть (без пробелов).
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        return "+7" + digits
    if raw.strip().startswith("+") and 10 <= len(digits) <= 15:
        return "+" + digits
    raise PhoneError("Укажите телефон в формате +7 999 123-45-67.")


class OrderCreate(BaseModel):
    quote_id: str
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=1, max_length=32)
    email: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=1000)
    comment: str | None = Field(default=None, max_length=2000)
    consent: bool = False  # согласие на обработку персональных данных
    company: Company | None = None  # заказ от юрлица или ИП (B33) → оплата по счёту

    @field_validator("email", "address", "comment", mode="before")
    @classmethod
    def _strip(cls, v):
        """Пробелы по краям убираем, пустую строку считаем «не указано»."""
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("name", mode="before")
    @classmethod
    def _name_required(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v:
            raise ValueError("Как к вам обращаться?")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        try:
            return normalize_phone(v)
        except PhoneError as e:
            raise ValueError(str(e)) from e

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is not None and not EMAIL_RE.match(v):
            raise ValueError("Проверьте e-mail.")
        return v


def session_email(request: Request, db: Db) -> str | None:
    """E-mail клиента, вошедшего в кабинет (cookie), или None."""
    from app.account import current_email  # account.py импортирует orders — без кольца

    return current_email(request, db)


@router.post("", status_code=201, dependencies=[Depends(orders_guard)])
def create_order(
    body: OrderCreate,
    db: Db,
    background: BackgroundTasks,
    logged_in_email: Annotated[str | None, Depends(session_email)] = None,
) -> dict:
    if not body.consent:
        raise HTTPException(status_code=422, detail="Нужно согласие на обработку данных.")
    quote = load_quote(body.quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Расчёт не найден. Рассчитайте цену заново.")
    if quote_is_expired(quote):
        raise HTTPException(status_code=410, detail=quote_expired_detail())
    # Один расчёт — один заказ: иначе повторные отправки формы плодят дубли,
    # а старый расчёт можно было бы заказывать бесконечно после смены цен.
    if db.scalar(select(Order.id).where(Order.quote_id == quote["id"]).limit(1)) is not None:
        raise HTTPException(
            status_code=409,
            detail="По этому расчёту заказ уже оформлен. "
            "Для нового заказа рассчитайте цену заново.",
        )
    if quote["delivery"] != "pickup" and not body.address:
        raise HTTPException(status_code=422, detail="Для доставки курьером нужен адрес.")
    email = body.email or logged_in_email
    if body.company is not None and not email:
        raise HTTPException(
            status_code=422, detail="Для заказа от организации нужен e-mail — на него уйдёт счёт."
        )

    order = Order(
        token=secrets.token_hex(16),
        customer_name=body.name,
        phone=body.phone,
        email=email,
        delivery=quote["delivery"],
        address=body.address if quote["delivery"] != "pickup" else None,
        comment=body.comment,
        upload_id=quote["upload_id"],
        quote_id=quote["id"],
        original_name=quote.get("original_name"),
        material=quote["material"],
        supports=bool(quote["supports"]),
        qty=int(quote["qty"]),
        postprocess=quote["postprocess"],
        total=int(round(quote["total"])),
        currency=quote.get("currency", "RUB"),
        quote=quote,
        # Организации платят по счёту (B33), частные лица — онлайн (B08).
        payment_method="invoice" if body.company is not None else "online",
        **(body.company.to_columns() if body.company is not None else {}),
    )
    db.add(order)
    db.flush()  # чтобы появился order.id
    # Воронка (B12): шаг «оформил заказ» — в той же транзакции, что и сам заказ.
    track(
        "order",
        db=db,
        upload_id=order.upload_id,
        quote_id=order.quote_id,
        order_id=order.id,
        props={
            "total": order.total,
            "delivery": order.delivery,
            "qty": order.qty,
            "payment_method": order.payment_method,
            "b2b": order.company_name is not None,
        },
    )
    db.commit()
    db.refresh(order)
    data = order.to_dict()
    # Владельцу — в Telegram, клиенту — письмо «принят» (B34); уже после ответа клиенту.
    background.add_task(notify_owner_new_order, data)
    background.add_task(notify.order_created, data)
    background.add_task(_push_to_sheet, order.id)  # B47: строка в Google-таблице учёта
    background.add_task(_push_to_drive, order.id)  # B46: файлы заказа в Google Drive
    return order_response(db, order)


def order_response(db: Session, order: Order) -> dict:
    """Заказ для клиента: поля таблицы + блок оплаты (B08) + блок уведомлений (B34)."""
    return order.to_dict() | {
        "payment": payment_summary(db, order),
        "notifications": notifications_summary(order),
    }


def notifications_summary(order: Order) -> dict:
    """Блок `notifications` (B34): на какой e-mail приходят статусы, подключён ли Telegram
    и ссылка на бота, по которой клиент его подключает (`/start <token заказа>`).
    Ссылки нет, если бот не настроен (нет токена) или Telegram уже подключён."""
    bot = tg.bot_username() if settings.telegram_bot_token else None
    linked = bool(order.telegram_chat_id)
    return {
        "email": order.email if order.email and settings.smtp_host else None,
        "telegram_linked": linked,
        "telegram_link": f"https://t.me/{bot}?start={order.token}" if bot and not linked else None,
    }


# --- оплата (B08): что про платёж видит страница статуса -----------------------


def latest_payment(db: Session, order: Order) -> Payment | None:
    """Последний по времени платёж заказа (или None, если оплату не начинали)."""
    return db.scalar(
        select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc()).limit(1)
    )


def payment_summary(db: Session, order: Order) -> dict:
    """Блок `payment` в ответе заказа: включена ли онлайн-оплата и в каком состоянии платёж.
    Заказ по счёту (B33) онлайн не платится — для него `enabled = false`."""
    enabled = bool(settings.yookassa_shop_id and settings.yookassa_secret_key)
    enabled = enabled and order.payment_method != "invoice"
    p = latest_payment(db, order)
    return {
        "enabled": enabled,
        "status": p.status if p else None,
        "confirmation_url": p.confirmation_url if p and p.status == "pending" else None,
        "paid_at": p.to_dict()["paid_at"] if p else None,
    }


# --- для бота (B07) и админки (B09) ------------------------------------------


class StatusError(ValueError):
    """Нельзя поставить такой статус (нет заказа, неизвестный статус, тот же статус)."""


def get_order_by_id(db: Session, order_id: int) -> Order | None:
    return db.get(Order, order_id)


def list_orders(db: Session, active_only: bool = True, limit: int = 20) -> list[Order]:
    """Заказы, новые сверху. active_only — только те, по которым есть работа."""
    q = select(Order)
    if active_only:
        q = q.where(Order.status.in_(ACTIVE_STATUSES))
    return list(db.scalars(q.order_by(Order.id.desc()).limit(limit)))


def change_status(db: Session, order_id: int, status: str, notify_client: bool = True) -> Order:
    """Поставить заказу статус. Любой переход разрешён — владелец знает, что делает;
    бот лишь предлагает кнопками логичные шаги (telegram.NEXT_STATUSES).
    После записи клиенту уходит уведомление (B34, в фоне); `notify_client=False` — без него."""
    if status not in ORDER_STATUSES:
        raise StatusError(f"Неизвестный статус «{status}».")
    order = get_order_by_id(db, order_id)
    if order is None:
        raise StatusError(f"Заказ № {order_id} не найден.")
    if order.status == status:
        raise StatusError(f"{order_number(order.id)} уже в статусе «{STATUS_LABELS[status]}».")
    order.status = status
    db.commit()
    db.refresh(order)
    if notify_client:
        notify.status_changed(order.to_dict())
    _push_to_sheet(order.id)  # B47: обновить строку заказа в Google-таблице учёта
    return order


def _push_to_sheet(order_id: int) -> None:
    # Импорт здесь, а не наверху: app.sheets сам импортирует app.orders (через app.export).
    from app import sheets

    sheets.push_order(order_id)


def _push_to_drive(order_id: int) -> None:
    from app import drive  # импорт здесь по той же причине, что и sheets

    drive.push_order(order_id)


def link_telegram(db: Session, token: str, chat_id: int | str) -> Order | None:
    """Клиент написал боту `/start <token>` (B34): запомнить его chat_id у заказа.
    None — такого заказа нет (ссылка не из нашего сайта)."""
    if not TOKEN_RE.match(token or ""):
        return None
    order = db.scalar(select(Order).where(Order.token == token))
    if order is None:
        return None
    order.telegram_chat_id = str(chat_id)
    db.commit()
    db.refresh(order)
    return order


def unlink_telegram(db: Session, chat_id: int | str) -> int:
    """Клиент написал боту /stop: больше не слать ему статусы. → сколько заказов отвязали."""
    orders = list(db.scalars(select(Order).where(Order.telegram_chat_id == str(chat_id))))
    for order in orders:
        order.telegram_chat_id = None
    db.commit()
    return len(orders)


def get_order_by_token(db: Session, token: str) -> Order:
    if not TOKEN_RE.match(token):
        raise HTTPException(status_code=404, detail="Заказ не найден.")
    order = db.scalar(select(Order).where(Order.token == token))
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден.")
    return order


@router.get("/{token}")
def get_order(token: str, db: Db) -> dict:
    order = get_order_by_token(db, token)
    return order_response(db, order)
