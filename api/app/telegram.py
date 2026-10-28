"""Telegram (B07): тексты и кнопки для владельца + отправка сообщений.

Здесь нет aiogram — только чистые функции и один HTTP-вызов Bot API через httpx.
Поэтому модуль одинаково годится и для API (уведомление о новом заказе из
`create_order`), и для бота (`app/bot.py`), который использует те же тексты и кнопки.

Схема данных в кнопках (callback_data, ≤64 байта):
- `order:<id>`            — показать карточку заказа;
- `status:<id>:<status>`  — поставить заказу статус;
- `orders`                — список активных заказов.
"""

import html
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx

from app.config import settings
from app.models import ORDER_STATUSES

log = logging.getLogger(__name__)

TG_API = "https://api.telegram.org"

STATUS_LABELS = {
    "new": "принят",
    "paid": "оплачен",
    "printing": "печатается",
    "ready": "готов",
    "done": "выдан",
    "cancelled": "отменён",
}
STATUS_ICONS = {
    "new": "🆕",
    "paid": "💰",
    "printing": "🖨",
    "ready": "✅",
    "done": "📦",
    "cancelled": "❌",
}
# Какие кнопки показывать для каждого статуса: обычный путь заказа + отмена.
# «Оплачен» из «принят» — на случай оплаты наличными при самовывозе (ЮKassa ставит paid сама, B08).
NEXT_STATUSES: dict[str, list[str]] = {
    "new": ["paid", "printing", "cancelled"],
    "paid": ["printing", "cancelled"],
    "printing": ["ready", "cancelled"],
    "ready": ["done", "cancelled"],
    "done": [],
    "cancelled": ["new"],
}
# Заказы в этих статусах показываем в /orders как «активные».
ACTIVE_STATUSES = ("new", "paid", "printing", "ready")

DELIVERY_LABELS = {"pickup": "самовывоз", "courier_moscow": "курьер по Москве"}
POSTPROCESS_LABELS = {"none": "нет", "sanding": "шлифовка"}

MSK = timedelta(hours=3)


def esc(value: object) -> str:
    """Экранируем текст клиента для parse_mode=HTML (имя, комментарий, адрес)."""
    return html.escape(str(value), quote=False)


def fmt_money(amount: int | float) -> str:
    return f"{int(round(amount)):,}".replace(",", " ") + " ₽"


def fmt_msk(iso: str | None) -> str:
    """ISO-дата из order.to_dict() → «19.10 23:41» по Москве."""
    if not iso:
        return ""
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (dt.astimezone(UTC) + MSK).strftime("%d.%m %H:%M")


def status_line(status: str) -> str:
    return f"{STATUS_ICONS.get(status, '•')} {STATUS_LABELS.get(status, status)}"


def order_card(order: dict, header: str | None = None) -> str:
    """Карточка заказа для владельца (HTML). `order` — результат Order.to_dict()."""
    lines = [
        f"<b>{esc(header or 'Заказ ' + order['number'])}</b> · {fmt_money(order['total'])}",
        f"Статус: {status_line(order['status'])}",
        f"{esc(order['customer_name'])}, {esc(order['phone'])}"
        + (f", {esc(order['email'])}" if order.get("email") else ""),
        f"{esc(order['material'])} × {order['qty']} шт"
        f" · поддержки: {'да' if order.get('supports') else 'нет'}"
        f" · постобработка: {POSTPROCESS_LABELS.get(order['postprocess'], order['postprocess'])}",
        f"Доставка: {DELIVERY_LABELS.get(order['delivery'], order['delivery'])}"
        + (f" — {esc(order['address'])}" if order.get("address") else ""),
    ]
    company = order.get("company")
    if company:
        # Заказ от организации (B33): кто покупатель и что платит по счёту, а не картой.
        lines.append(
            f"Юрлицо: {esc(company['name'])}, ИНН {esc(company['inn'])}"
            + (f", КПП {esc(company['kpp'])}" if company.get("kpp") else "")
            + " · оплата по счёту"
        )
    quote = order.get("quote") or {}
    if quote.get("print_time_s") or quote.get("material_g"):
        hours = (quote.get("print_time_s") or 0) / 3600 * order["qty"]
        grams = (quote.get("material_g") or 0) * order["qty"]
        lines.append(f"Печать: ~{hours:.1f} ч, {grams:.0f} г на весь тираж")
    if order.get("original_name"):
        lines.append(f"Файл: {esc(order['original_name'])}")
    if quote.get("decor"):
        # Раскраска по частям (B31) или тиснение (B30): «Деталь 1 — красный, Деталь 2 — синий».
        lines.append(f"Оформление: {esc(quote['decor'])}")
    if order.get("comment"):
        lines.append(f"Комментарий: {esc(order['comment'])}")
    if order.get("telegram_chat_id"):
        # Клиент подключил бота (B34): смена статуса кнопкой уйдёт ему и в Telegram.
        lines.append("Статусы клиенту: Telegram" + (" и e-mail" if order.get("email") else ""))
    created = fmt_msk(order.get("created_at"))
    if created:
        lines.append(f"Создан: {created} МСК")
    lines.append(order_links(order))
    return "\n".join(lines)


def admin_order_url(order_id: int) -> str:
    """Карточка заказа в админке (B09)."""
    return f"{settings.site_url.rstrip('/')}/admin/orders/{order_id}"


def order_links(order: dict) -> str:
    """Последняя строка карточки (B48): ссылки одним касанием.

    - «Страница заказа» — то, что видит клиент;
    - «Админка» — только если админка включена (`ADMIN_PASSWORD` задан), иначе ссылка вела бы в 503;
    - «Файлы в Drive» — если заказ уже скопирован в Google Drive (B46, `drive_folder_url`).
    """
    site = settings.site_url.rstrip("/")
    links = [f'<a href="{esc(site)}/order/{esc(order["token"])}">Страница заказа</a>']
    if settings.admin_user and settings.admin_password:
        links.append(f'<a href="{esc(admin_order_url(order["id"]))}">Админка</a>')
    if order.get("drive_folder_url"):
        links.append(f'<a href="{esc(order["drive_folder_url"])}">Файлы в Drive</a>')
    return " · ".join(links)


def order_keyboard(order: dict) -> dict:
    """Кнопки смены статуса под карточкой (формат Bot API: inline_keyboard)."""
    buttons = [
        {
            "text": f"{STATUS_ICONS[s]} {STATUS_LABELS[s].capitalize()}",
            "callback_data": f"status:{order['id']}:{s}",
        }
        for s in NEXT_STATUSES.get(order["status"], [])
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([{"text": "📋 Активные заказы", "callback_data": "orders"}])
    return {"inline_keyboard": rows}


def orders_list(orders: list[dict], title: str = "Активные заказы") -> tuple[str, dict]:
    """Список заказов одним сообщением + кнопка на карточку каждого."""
    if not orders:
        return f"<b>{esc(title)}</b>\nПока пусто.", {"inline_keyboard": []}
    lines = [f"<b>{esc(title)}</b>"]
    for o in orders:
        lines.append(
            f"{STATUS_ICONS.get(o['status'], '•')} <b>{o['number']}</b> · "
            f"{esc(o['customer_name'])} · {esc(o['material'])} × {o['qty']} · "
            f"{fmt_money(o['total'])} · {fmt_msk(o.get('created_at'))}"
        )
    buttons = [{"text": o["number"], "callback_data": f"order:{o['id']}"} for o in orders]
    rows = [buttons[i : i + 4] for i in range(0, len(buttons), 4)]
    return "\n".join(lines), {"inline_keyboard": rows}


def parse_callback(data: str) -> tuple[str, int | None, str | None]:
    """«status:12:paid» → («status», 12, «paid»); «order:12» → («order», 12, None).

    Непонятное → («?», None, None), бот просто отвечает «не понял».
    """
    parts = (data or "").split(":")
    try:
        if parts[0] == "orders" and len(parts) == 1:
            return "orders", None, None
        if parts[0] == "order" and len(parts) == 2:
            return "order", int(parts[1]), None
        if parts[0] == "status" and len(parts) == 3 and parts[2] in ORDER_STATUSES:
            return "status", int(parts[1]), parts[2]
    except ValueError:
        pass
    return "?", None, None


# --- отправка ----------------------------------------------------------------


def telegram_enabled() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_owner_chat_id)


# Повторы при сбоях сети (B48): после 1-й неудачи ждём 1 с, после 2-й — 3 с, потом сдаёмся.
# Повторяем только то, что может пройти со второго раза: обрыв сети, 429 (Telegram просит
# подождать — ждём сколько скажет, но не больше 10 с) и 5xx. 400/401/403 — ошибка в запросе
# или токене, повтор не поможет.
RETRY_DELAYS_S = (1, 3)
MAX_RETRY_AFTER_S = 10


def _retry_delay(r: httpx.Response | None, default: float) -> float | None:
    """Сколько ждать перед повтором; None — повторять бессмысленно."""
    if r is None or r.status_code >= 500:
        return default
    if r.status_code == 429:
        try:
            after = (r.json().get("parameters") or {}).get("retry_after") or default
        except ValueError:
            after = default
        return min(float(after), MAX_RETRY_AFTER_S)
    return None


def send_message(chat_id: str | int, text: str, reply_markup: dict | None = None) -> bool:
    """sendMessage с повторами при сбоях сети. Ошибки не роняют вызывающий код — только лог."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    url = f"{TG_API}/bot{settings.telegram_bot_token}/sendMessage"
    for attempt in range(len(RETRY_DELAYS_S) + 1):
        r: httpx.Response | None = None
        try:
            r = httpx.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                return True
            log.warning("telegram sendMessage %s: %s", r.status_code, r.text[:200])
        except httpx.HTTPError as e:
            log.warning("telegram sendMessage failed: %s", e)
        if attempt == len(RETRY_DELAYS_S):
            break
        delay = _retry_delay(r, RETRY_DELAYS_S[attempt])
        if delay is None:
            break
        time.sleep(delay)
    return False


# Имя бота (@username) для ссылки «Получать статусы в Telegram» (B34): спрашиваем у Telegram
# один раз (getMe) и помним. Если Telegram не ответил — пробуем снова не раньше чем через 5 минут.
# `checked_at` — время последней попытки (time.monotonic) или None, если ещё не спрашивали.
# Именно None, а не 0: monotonic считает от загрузки системы, и на свежей машине (CI) она
# меньше 5 минут — с нулём кэш думал бы, что «только что спрашивали», и не ходил в Telegram.
_bot_username: dict = {"name": None, "checked_at": None}
BOT_USERNAME_RETRY_S = 300


def bot_username() -> str | None:
    """@username бота без «@» или None (нет токена / Telegram не ответил)."""
    if not settings.telegram_bot_token:
        return None
    cache = _bot_username
    if cache["name"]:
        return cache["name"]
    asked_at = cache["checked_at"]
    if asked_at is not None and time.monotonic() - asked_at < BOT_USERNAME_RETRY_S:
        return None  # недавно не ответил — не дёргаем Telegram снова
    cache["checked_at"] = time.monotonic()
    try:
        r = httpx.get(f"{TG_API}/bot{settings.telegram_bot_token}/getMe", timeout=10)
        if r.status_code == 200:
            cache["name"] = (r.json().get("result") or {}).get("username") or None
        else:
            log.warning("telegram getMe %s: %s", r.status_code, r.text[:200])
    except (httpx.HTTPError, ValueError) as e:
        log.warning("telegram getMe failed: %s", e)
    return cache["name"]


def forget_bot_username() -> None:
    """Сбросить кэш getMe (для тестов и смены токена)."""
    _bot_username.update(name=None, checked_at=None)


def notify_owner_new_order(order: dict) -> bool:
    """Сообщение владельцу о новом заказе с кнопками статусов.

    Вызывается из API в фоне после ответа клиенту (BackgroundTasks).
    Без TELEGRAM_BOT_TOKEN / TELEGRAM_OWNER_CHAT_ID ничего не делает.
    """
    if not telegram_enabled():
        log.info("telegram выключен (нет токена/chat_id): заказ %s без уведомления", order["id"])
        return False
    text = order_card(order, header=f"🆕 Новый заказ {order['number']}")
    return send_message(settings.telegram_owner_chat_id, text, order_keyboard(order))


def notify_owner_paid(order: dict) -> bool:
    """Сообщение владельцу: заказ оплачен через ЮKassa (B08). Кнопки — следующие шаги."""
    if not telegram_enabled():
        log.info("telegram выключен: оплата заказа %s без уведомления", order["id"])
        return False
    text = order_card(order, header=f"💰 Оплачен заказ {order['number']}")
    if order["status"] != "paid":
        # Деньги пришли по заказу, который уже не «принят» (например, отменён) — решает владелец.
        label = STATUS_LABELS.get(order["status"], order["status"])
        text += f"\n⚠️ Заказ сейчас в статусе «{label}»."
    return send_message(settings.telegram_owner_chat_id, text, order_keyboard(order))
