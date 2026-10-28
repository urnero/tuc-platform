"""Таблицы БД: `orders` (B06; реквизиты юрлица и способ оплаты — B33; Telegram клиента — B34),
`payments` (B08), `events` (B12), `login_codes` и `client_sessions` (кабинет клиента, B32).
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

# Как клиент платит (B33): online — картой через ЮKassa (B08); invoice — по счёту безналом,
# так платят организации и ИП; «оплачен» тогда ставит владелец, когда деньги пришли на счёт.
PAYMENT_METHODS = ("online", "invoice")

# Статусы платежа — те же слова, что у ЮKassa: создан → (ждёт подтверждения) → успех | отменён.
PAYMENT_STATUSES = ("pending", "waiting_for_capture", "succeeded", "canceled")

# Шаги воронки (B12) по порядку. Пишутся в `events` сервером в момент, когда шаг случился:
# upload — клиент загрузил модель; quote — посчитал цену; order — оформил заказ;
# payment_started — нажал «Оплатить» (создан платёж в ЮKassa); paid — оплата прошла.
# editor_build — не шаг воронки: клиент построил модель в редакторе (B21), это ещё до загрузки.
# emboss_build / paint_build — тоже не шаги: клиент запустил тиснение (B30) / раскраску (B31).
# account_login — клиент вошёл в кабинет по коду из письма (B32); не шаг воронки.
# material_request — заявка «цена по запросу» (смолы, B44); контакты в props; не шаг воронки.
EVENT_NAMES = (
    "upload",
    "quote",
    "order",
    "payment_started",
    "paid",
    "editor_build",
    "emboss_build",
    "paint_build",
    "account_login",
    "material_request",
)


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

    # Юрлицо или ИП (B33): заполнены, если клиент заказывает от организации. Остальным — NULL.
    company_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    company_inn: Mapped[str | None] = mapped_column(String(12), nullable=True)  # 10 или 12 цифр
    company_kpp: Mapped[str | None] = mapped_column(String(9), nullable=True)  # у организаций
    company_address: Mapped[str | None] = mapped_column(Text, nullable=True)  # юридический адрес
    # online | invoice (PAYMENT_METHODS). У заказов до B33 — online.
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False, default="online")
    # Куда слать клиенту статусы в Telegram (B34): chat_id, если клиент нажал «Получать статусы
    # в Telegram» на странице заказа и написал боту /start <token>. NULL — только e-mail.
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Обезличивание (B35): через 5 лет после закрытия заказа ночной cron (app/anonymize.py)
    # стирает имя, телефон, e-mail, адрес, комментарий, реквизиты и chat_id и ставит сюда дату.
    # NULL — данные клиента на месте. Суммы, материал, снимок расчёта остаются для аналитики.
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
        from app.orders import order_number  # внутри: orders.py сам импортирует models

        return {
            "id": self.id,
            "number": order_number(self.id),
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
            "company": self.company_dict(),
            "payment_method": self.payment_method,
            "telegram_chat_id": self.telegram_chat_id,
            "anonymized_at": _iso(self.anonymized_at) if self.anonymized_at else None,
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

    def company_dict(self) -> dict | None:
        """Реквизиты покупателя-юрлица для счёта (B33); None — заказ от частного лица."""
        if not self.company_name:
            return None
        return {
            "name": self.company_name,
            "inn": self.company_inn,
            "kpp": self.company_kpp,
            "address": self.company_address,
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


class Event(Base):
    """Событие воронки (B12): одна строка на шаг. Таблица только дописывается, строки не меняются.

    Как склеить шаги в воронку: upload → quote → order связаны через `upload_id`
    (одна загрузка — один клиентский путь), payment_started и paid — через `order_id`
    (у заказа `upload_id` тоже заполнен). Пример SQL — в docs/ANALYTICS.md.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # из EVENT_NAMES
    upload_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    quote_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Без внешнего ключа: события — журнал, он должен пережить удаление заказа.
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Детали шага: у upload — расширение, размер, предупреждения сетки; у quote — материал,
    # тираж, сумма; у order — сумма, доставка; у paid — сумма. Ключи — в app/events.py.
    props: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": _iso(self.created_at),
            "name": self.name,
            "upload_id": self.upload_id,
            "quote_id": self.quote_id,
            "order_id": self.order_id,
            "props": self.props,
        }


class LoginCode(Base):
    """Код для входа в кабинет (B32): одна строка на письмо. Хранится не сам код, а его
    sha256 — утечка БД не даёт войти. Код живёт LOGIN_CODE_TTL_MIN минут, 5 попыток, один раз."""

    __tablename__ = "login_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)  # строчными
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientSession(Base):
    """Вход клиента в кабинет (B32): token лежит в cookie `tuc_session` (HttpOnly).
    Выход — строка удаляется. Срок — SESSION_DAYS дней от входа."""

    __tablename__ = "client_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)  # строчными
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _iso(dt: datetime) -> str:
    """SQLite теряет часовой пояс — считаем, что всё хранится в UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")
