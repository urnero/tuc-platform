"""Таблицы БД: `orders` (B06) и `payments` (B08).
Изменил таблицу → добавь миграцию в alembic/versions/.

Загрузки, расчёты печати и цены по-прежнему лежат файлами в DATA_DIR (см. DECISIONS.md):
заказ хранит их id и снимок расчёта цены, чтобы цена в заказе не менялась,
если владелец поправит pricing.yaml.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Статусы заказа по порядку. Меняет их владелец (бот B07, админка B09), оплата (B08) ставит paid.
ORDER_STATUSES = ("new", "paid", "printing", "ready", "done", "cancelled")

# Статусы платежа — те же слова, что у ЮKassa: создан → (ждёт подтверждения) → успех | отменён.
PAYMENT_STATUSES = ("pending", "waiting_for_capture", "succeeded", "canceled")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Order(Base):
    __tablename__ = "orders"

    # Номер заказа — его видит владелец и клиент («Заказ № 12»).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Секретная часть ссылки на страницу статуса: /order/<token>. Угадать нельзя.
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # Клиент
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)  # нормализован: +7XXXXXXXXXX
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    delivery: Mapped[str] = mapped_column(String(32), nullable=False)  # pickup | courier_moscow
    address: Mapped[str | None] = mapped_column(Text, nullable=True)  # адрес, если курьер
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Что печатаем: ссылки на файлы в DATA_DIR и ключевые поля расчёта (удобно для SQL)
    upload_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    material: Mapped[str] = mapped_column(String(20), nullable=False)
    supports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    postprocess: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    total: Mapped[int] = mapped_column(Integer, nullable=False)  # ₽ на момент заказа
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    # Полный снимок ответа /quote: ставки и разложение суммы, как их видел клиент.
    quote: Mapped[dict] = mapped_column(JSON, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "number": f"ТУЦ-{self.id}",
            "token": self.token,
            "status": self.status,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "customer_name": self.customer_name,
            "phone": self.phone,
            "email": self.email,
            "delivery": self.delivery,
            "address": self.address,
            "comment": self.comment,
            "upload_id": self.upload_id,
            "quote_id": self.quote_id,
            "original_name": self.original_name,
            "material": self.material,
            "supports": self.supports,
            "qty": self.qty,
            "postprocess": self.postprocess,
            "total": self.total,
            "currency": self.currency,
            "quote": self.quote,
        }


class Payment(Base):
    """Платёж ЮKassa (B08). Одна строка на попытку оплаты; у заказа их может быть несколько
    (клиент передумал, вернулся позже), но «успешный» — максимум один."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # id платежа в ЮKassa (строка вида 2d1e…-000f-5000-8000-…). По нему ищем платёж из вебхука.
    yookassa_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # Ключ идемпотентности, который мы отправили в ЮKassa при создании платежа.
    idempotence_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # ₽, равно order.total
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    # Куда отправить клиента платить (форма ЮKassa). Пусто, когда платёж уже завершён.
    confirmation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    # Последний ответ ЮKassa про этот платёж целиком — чтобы разбирать спорные случаи.
    raw: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "yookassa_id": self.yookassa_id,
            "status": self.status,
            "amount": self.amount,
            "currency": self.currency,
            "confirmation_url": self.confirmation_url,
            "paid_at": _iso(self.paid_at) if self.paid_at else None,
            "created_at": _iso(self.created_at),
        }


def _iso(dt: datetime) -> str:
    """SQLite теряет часовой пояс — считаем, что всё хранится в UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")
