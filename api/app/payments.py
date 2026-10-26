"""Оплата через ЮKassa (B08).

POST /api/v1/orders/{token}/payment        — создать платёж (или вернуть уже начатый).
                                              Ответ: платёж + confirmation_url, куда
                                              отправить клиента на форму ЮKassa.
POST /api/v1/orders/{token}/payment/check  — сверить платёж с ЮKassa. Зовёт страница статуса,
                                              когда клиент вернулся с формы оплаты: так заказ
                                              станет «оплачен» даже если вебхук ещё не дошёл
                                              (или его нет — локальный запуск без домена).
POST /api/v1/payments/yookassa/webhook     — уведомление от ЮKassa (payment.succeeded /
                                              payment.canceled). Этот адрес (с SITE_URL в начале)
                                              вписывается в кабинете ЮKassa → HTTP-уведомления.

Как это работает:
1. Заказ в статусе «принят» → клиент жмёт «Оплатить» → мы создаём платёж в ЮKassa
   (REST API v3, capture=true — деньги списываются сразу, без двухстадийного подтверждения)
   и сохраняем строку в таблице `payments`.
2. Клиент платит на странице ЮKassa и возвращается на /order/<token>?payment=check.
3. Статус платежа мы узнаём ДВУМЯ путями — вебхуком и запросом /check при возвращении —
   и оба раза не верим присланному телу, а перечитываем платёж из ЮKassa по его id
   (`GET /v3/payments/{id}`). Вебхуки ЮKassa не подписаны, так что это и защита от
   подделки, и единственный источник правды.
4. Платёж `succeeded` → заказ «оплачен» (`orders.change_status`) + сообщение владельцу
   в Telegram. Повторный вебхук про тот же платёж ничего не меняет (идемпотентность:
   смотрим на статус строки в `payments`, а не на событие).

Без YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY оплата выключена: /payment отвечает 503,
на странице статуса кнопки нет (поле `payment.enabled` в ответе заказа).
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.events import track
from app.models import PAYMENT_STATUSES, Order, Payment
from app.orders import change_status, get_order_by_token, latest_payment
from app.telegram import notify_owner_paid

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["payments"])
Db = Annotated[Session, Depends(get_db)]
# Тело вебхука ЮKassa как есть (словарь): проверяем поля сами, а не схемой —
# ЮKassa может добавлять новые поля, и падать на них не нужно.
WebhookBody = Annotated[dict, Body()]

# Тесты подменяют транспорт httpx, чтобы вместо настоящей ЮKassa отвечал поддельный сервер.
TRANSPORT: httpx.BaseTransport | None = None

# Заказ можно оплатить онлайн только пока он «принят»: дальше либо уже оплачен,
# либо отменён, либо владелец отметил оплату сам (наличными при самовывозе).
PAYABLE_STATUSES = ("new",)


class YooKassaError(Exception):
    """ЮKassa ответила ошибкой или недоступна."""


def payments_enabled() -> bool:
    return bool(settings.yookassa_shop_id and settings.yookassa_secret_key)


# --- запросы в ЮKassa ---------------------------------------------------------


def _client() -> httpx.Client:
    """HTTP-клиент к ЮKassa: Basic-авторизация «shopId:секретный ключ»."""
    return httpx.Client(
        base_url=settings.yookassa_api_url,
        auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
        timeout=20,
        transport=TRANSPORT,
    )


def _call(method: str, path: str, json: dict | None = None, headers: dict | None = None) -> dict:
    try:
        with _client() as c:
            r = c.request(method, path, json=json, headers=headers)
    except httpx.HTTPError as e:
        raise YooKassaError(f"ЮKassa недоступна: {e}") from e
    if r.status_code >= 400:
        log.warning("yookassa %s %s → %s: %s", method, path, r.status_code, r.text[:300])
        raise YooKassaError(f"ЮKassa ответила {r.status_code}: {r.text[:200]}")
    return r.json()


def fmt_amount(rub: int | float) -> str:
    """1234 → «1234.00» (формат суммы в ЮKassa)."""
    return f"{float(rub):.2f}"


def build_payment_request(order: Order) -> dict:
    """Тело запроса на создание платежа. Чистая функция — проверяется тестом."""
    body = {
        "amount": {"value": fmt_amount(order.total), "currency": order.currency},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": f"{settings.site_url}/order/{order.token}?payment=check",
        },
        "description": f"Заказ ТУЦ-{order.id}: 3D-печать, {order.material} × {order.qty} шт",
        "metadata": {"order_id": str(order.id)},
    }
    if settings.yookassa_vat_code:
        # Чек 54-ФЗ: одна позиция на весь заказ (печать + постобработка + доставка).
        customer = {"phone": order.phone.lstrip("+")}
        if order.email:
            customer["email"] = order.email
        body["receipt"] = {
            "customer": customer,
            "items": [
                {
                    "description": f"3D-печать по заказу ТУЦ-{order.id}",
                    "quantity": "1.00",
                    "amount": body["amount"],
                    "vat_code": int(settings.yookassa_vat_code),
                    "payment_subject": "service",
                    "payment_mode": "full_payment",
                }
            ],
        }
    return body


def yk_create_payment(order: Order, idempotence_key: str) -> dict:
    """POST /v3/payments. Повтор с тем же Idempotence-Key вернёт тот же платёж."""
    return _call(
        "POST",
        "/payments",
        json=build_payment_request(order),
        headers={"Idempotence-Key": idempotence_key},
    )


def yk_get_payment(yookassa_id: str) -> dict:
    """GET /v3/payments/{id} — актуальное состояние платежа."""
    return _call("GET", f"/payments/{yookassa_id}")


# --- наша сторона ----------------------------------------------------------------


def apply_payment_object(db: Session, payment: Payment, obj: dict) -> bool:
    """Записать в строку платежа то, что сказала ЮKassa.

    Возвращает True, если платёж ТОЛЬКО ЧТО стал успешным (заказ переведён в «оплачен»);
    при повторном вызове с тем же результатом — False. На этом держится идемпотентность.
    """
    status = obj.get("status")
    if status not in PAYMENT_STATUSES:
        raise YooKassaError(f"Неизвестный статус платежа «{status}».")
    was_succeeded = payment.status == "succeeded"
    payment.status = status
    payment.raw = obj
    confirmation = obj.get("confirmation") or {}
    payment.confirmation_url = confirmation.get("confirmation_url") if status == "pending" else None
    just_paid = status == "succeeded" and not was_succeeded
    if just_paid:
        payment.paid_at = _parse_dt(obj.get("captured_at")) or datetime.now(UTC)
        order = db.get(Order, payment.order_id)
        if order is not None and order.status in PAYABLE_STATUSES:
            change_status(db, order.id, "paid")
        # Воронка (B12): шаг «оплатил». Пишется один раз — только при переходе в succeeded.
        track(
            "paid",
            db=db,
            upload_id=order.upload_id if order else None,
            order_id=payment.order_id,
            props={"amount": payment.amount, "yookassa_id": payment.yookassa_id},
        )
    db.commit()
    db.refresh(payment)
    return just_paid


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def sync_payment(db: Session, payment: Payment) -> bool:
    """Перечитать платёж из ЮKassa и применить. True — заказ только что стал оплаченным."""
    return apply_payment_object(db, payment, yk_get_payment(payment.yookassa_id))


def start_payment(db: Session, order: Order) -> Payment:
    """Вернуть платёж, по которому клиента можно отправить платить: начатый или новый."""
    last = latest_payment(db, order)
    if last is not None and last.status == "succeeded":
        raise HTTPException(status_code=409, detail="Заказ уже оплачен.")
    if order.status not in PAYABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Этот заказ сейчас нельзя оплатить онлайн.")
    if last is not None and last.status == "pending":
        # Клиент уже начинал платить: сверяемся с ЮKassa, и если форма ещё открыта — она же.
        try:
            sync_payment(db, last)
        except YooKassaError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        if last.status == "succeeded":
            raise HTTPException(status_code=409, detail="Заказ уже оплачен.")
        if last.status == "pending" and last.confirmation_url:
            return last

    key = str(uuid.uuid4())
    try:
        obj = yk_create_payment(order, key)
    except YooKassaError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    payment = Payment(
        order_id=order.id,
        yookassa_id=obj["id"],
        idempotence_key=key,
        status="pending",
        amount=order.total,
        currency=order.currency,
        raw={},
    )
    db.add(payment)
    db.flush()
    # Воронка (B12): шаг «нажал „Оплатить“» — платёж в ЮKassa создан, клиент ушёл на форму.
    track(
        "payment_started",
        db=db,
        upload_id=order.upload_id,
        order_id=order.id,
        props={"amount": payment.amount, "yookassa_id": payment.yookassa_id},
    )
    apply_payment_object(db, payment, obj)
    return payment


def _notify_paid(order_id: int) -> None:
    """Сообщение владельцу в Telegram — в фоне, после ответа. Своя сессия БД."""
    db = next(get_db())
    try:
        order = db.get(Order, order_id)
        if order is not None:
            notify_owner_paid(order.to_dict())
    finally:
        db.close()


def _require_enabled() -> None:
    if not payments_enabled():
        raise HTTPException(status_code=503, detail="Онлайн-оплата пока не подключена.")


@router.post("/orders/{token}/payment", status_code=201)
def create_payment(token: str, db: Db) -> dict:
    _require_enabled()
    order = get_order_by_token(db, token)
    payment = start_payment(db, order)
    return {"payment": payment.to_dict(), "confirmation_url": payment.confirmation_url}


@router.post("/orders/{token}/payment/check")
def check_payment(token: str, db: Db, background: BackgroundTasks) -> dict:
    """Клиент вернулся с формы ЮKassa — узнаём, чем всё кончилось."""
    _require_enabled()
    order = get_order_by_token(db, token)
    payment = latest_payment(db, order)
    if payment is None:
        raise HTTPException(status_code=404, detail="По этому заказу оплата не начиналась.")
    if payment.status in ("pending", "waiting_for_capture"):
        try:
            if sync_payment(db, payment):
                background.add_task(_notify_paid, order.id)
        except YooKassaError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
    db.refresh(order)
    return {"payment": payment.to_dict(), "order_status": order.status}


@router.post("/payments/yookassa/webhook")
def yookassa_webhook(body: WebhookBody, db: Db, background: BackgroundTasks) -> dict:
    """ЮKassa шлёт {type: notification, event: payment.succeeded, object: {id, …}}.

    Всегда отвечаем 200, чтобы ЮKassa не повторяла уведомление: неизвестный платёж
    (например, от другого окружения с тем же магазином) просто пропускаем.

    Обработчик — обычный `def`, не `async`: внутри синхронный запрос в ЮKassa (до 20 с)
    и работа с БД. Синхронную функцию FastAPI выполняет в отдельном потоке, и остальные
    запросы (например, /health или загрузка модели) не ждут ответа ЮKassa. Тело разбирает
    сам FastAPI (`Body`): не JSON или не объект → 422.
    """
    _require_enabled()
    event = str(body.get("event", ""))
    obj = body.get("object") or {}
    if not event.startswith("payment.") or not obj.get("id"):
        log.info("yookassa webhook: пропускаем событие %s", event or "?")
        return {"ok": True, "ignored": True}
    payment = db.query(Payment).filter(Payment.yookassa_id == str(obj["id"])).one_or_none()
    if payment is None:
        log.warning("yookassa webhook: неизвестный платёж %s", obj["id"])
        return {"ok": True, "ignored": True}
    try:
        just_paid = sync_payment(db, payment)
    except YooKassaError as e:
        # 5xx — ЮKassa повторит уведомление позже, когда её API снова ответит.
        raise HTTPException(status_code=502, detail=str(e)) from e
    if just_paid:
        background.add_task(_notify_paid, payment.order_id)
    return {"ok": True, "status": payment.status, "order_id": payment.order_id}
