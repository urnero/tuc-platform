"""Заказы (B06).

POST /api/v1/orders            — оформить заказ по расчёту цены: {quote_id, name, phone,
                                  email?, address?, comment?, consent}. Доставка берётся из
                                  расчёта; если курьер — адрес обязателен. Ответ: заказ с token.
GET  /api/v1/orders/{token}    — заказ для страницы статуса /order/<token>. Ссылку знает
                                  только клиент (token случайный), логина пока нет.

Заказ — строка в таблице `orders` (app/models.py). Цена фиксируется снимком расчёта.
После создания заказа владельцу уходит сообщение в Telegram (B07, `app/telegram.py`) —
в фоне, после ответа клиенту, чтобы сбой Telegram не ломал оформление.
Оплата (B08) — `app/payments.py`: в ответе заказа есть блок `payment`
(включена ли онлайн-оплата, статус платежа, ссылка на форму ЮKassa).

Смена статуса — `change_status()`: её зовёт бот (B07), ЮKassa (B08, ставит paid),
админка (B09, `app/admin.py`).
"""

import re
import secrets
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.events import track
from app.models import ORDER_STATUSES, Order, Payment
from app.quotes import load_quote
from app.telegram import ACTIVE_STATUSES, STATUS_LABELS, notify_owner_new_order

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])
Db = Annotated[Session, Depends(get_db)]  # сессия БД на запрос

TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PhoneError(ValueError):
    pass


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


@router.post("", status_code=201)
def create_order(body: OrderCreate, db: Db, background: BackgroundTasks) -> dict:
    if not body.consent:
        raise HTTPException(status_code=422, detail="Нужно согласие на обработку данных.")
    quote = load_quote(body.quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Расчёт не найден. Рассчитайте цену заново.")
    if quote["delivery"] != "pickup" and not body.address:
        raise HTTPException(status_code=422, detail="Для доставки курьером нужен адрес.")

    order = Order(
        token=secrets.token_hex(16),
        customer_name=body.name,
        phone=body.phone,
        email=body.email,
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
        props={"total": order.total, "delivery": order.delivery, "qty": order.qty},
    )
    db.commit()
    db.refresh(order)
    data = order.to_dict()
    # Владельцу — в Telegram, уже после того, как клиент получил ответ.
    background.add_task(notify_owner_new_order, data)
    return data | {"payment": payment_summary(db, order)}


# --- оплата (B08): что про платёж видит страница статуса -----------------------


def latest_payment(db: Session, order: Order) -> Payment | None:
    """Последний по времени платёж заказа (или None, если оплату не начинали)."""
    return db.scalar(
        select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc()).limit(1)
    )


def payment_summary(db: Session, order: Order) -> dict:
    """Блок `payment` в ответе заказа: включена ли онлайн-оплата и в каком состоянии платёж."""
    enabled = bool(settings.yookassa_shop_id and settings.yookassa_secret_key)
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


def change_status(db: Session, order_id: int, status: str) -> Order:
    """Поставить заказу статус. Любой переход разрешён — владелец знает, что делает;
    бот лишь предлагает кнопками логичные шаги (telegram.NEXT_STATUSES)."""
    if status not in ORDER_STATUSES:
        raise StatusError(f"Неизвестный статус «{status}».")
    order = get_order_by_id(db, order_id)
    if order is None:
        raise StatusError(f"Заказ № {order_id} не найден.")
    if order.status == status:
        raise StatusError(f"ТУЦ-{order.id} уже в статусе «{STATUS_LABELS[status]}».")
    order.status = status
    db.commit()
    db.refresh(order)
    return order


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
    return order.to_dict() | {"payment": payment_summary(db, order)}
