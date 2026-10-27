"""Telegram-бот владельца (B07, aiogram 3). Запуск: `python -m app.bot`.

В docker-compose это сервис `bot` — тот же образ, что api, другая команда.
Бот ходит в Telegram сам (long polling), публичный адрес и вебхук ему не нужны.

Что умеет (только для владельца — чат с id TELEGRAM_OWNER_CHAT_ID):
- /start, /help      — подсказка;
- /orders            — активные заказы (принят, оплачен, печатается, готов), новые сверху;
- /orders all        — последние 20 заказов любых статусов;
- /order 12          — карточка заказа ТУЦ-12 с кнопками статусов;
- кнопки под карточкой — поставить статус (запись в таблицу orders), карточка обновляется.

Уведомление о новом заказе шлёт не бот, а API (`app/telegram.py::notify_owner_new_order`),
но кнопки под ним те же — нажатия обрабатывает этот бот.
Тексты и кнопки — в `app/telegram.py`, здесь только связка с aiogram и БД.

Клиенты (B34): на странице заказа кнопка «Получать статусы в Telegram» открывает бота
со ссылкой `t.me/<бот>?start=<token заказа>` — Telegram шлёт `/start <token>`, бот записывает
chat_id клиента в заказ (`orders.link_telegram`), дальше статусы приходят ему сообщениями
(`app/notify.py`). `/stop` — отписаться. Остальное для клиентов недоступно.
"""

import asyncio
import logging
from collections.abc import Callable

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.orm import Session

from app import notify
from app import telegram as tg
from app.config import settings
from app.db import session_factory
from app.orders import (
    StatusError,
    change_status,
    get_order_by_id,
    link_telegram,
    list_orders,
    unlink_telegram,
)

log = logging.getLogger(__name__)

HELP = (
    "<b>Бот студии ТУЦ</b>\n"
    "/orders — активные заказы\n"
    "/orders all — последние 20 заказов\n"
    "/order 12 — карточка заказа ТУЦ-12\n"
    "/stop — не получать сюда статусы заказов (для клиентов)\n"
    "Кнопки под карточкой меняют статус заказа."
)
NOT_OWNER = (
    "Этот бот присылает статусы заказов студии ТУЦ. Чтобы подключить уведомления, нажмите "
    "«Получать статусы в Telegram» на странице вашего заказа. Отписаться — /stop."
)
NOT_LINKED = "Такого заказа нет. Откройте страницу заказа на сайте и нажмите кнопку там ещё раз."


def owner_id() -> int | None:
    """TELEGRAM_OWNER_CHAT_ID → число; пусто или не число → None (бот никого не слушает)."""
    raw = (settings.telegram_owner_chat_id or "").strip()
    try:
        return int(raw)
    except ValueError:
        return None


def is_owner(user_id: int | None) -> bool:
    oid = owner_id()
    return oid is not None and user_id == oid


def kb(markup: dict) -> InlineKeyboardMarkup:
    """Словарь из app/telegram.py → объект aiogram."""
    return InlineKeyboardMarkup.model_validate(markup)


async def in_db[T](fn: Callable[[Session], T]) -> T:
    """Запрос к БД в отдельном потоке: SQLAlchemy у нас синхронный, бот — асинхронный."""

    def run() -> T:
        db = session_factory()()
        try:
            return fn(db)
        finally:
            db.close()

    return await asyncio.to_thread(run)


# --- ответы (их удобно тестировать без Telegram) ------------------------------


def orders_reply(db: Session, active_only: bool = True) -> tuple[str, dict]:
    orders = [o.to_dict() for o in list_orders(db, active_only=active_only, limit=20)]
    title = "Активные заказы" if active_only else "Последние 20 заказов"
    return tg.orders_list(orders, title=title)


def order_reply(db: Session, order_id: int) -> tuple[str, dict]:
    order = get_order_by_id(db, order_id)
    if order is None:
        return f"Заказ № {order_id} не найден.", {"inline_keyboard": []}
    data = order.to_dict()
    return tg.order_card(data), tg.order_keyboard(data)


def status_reply(db: Session, order_id: int, status: str) -> tuple[str, dict, str]:
    """→ (текст карточки, кнопки, короткий ответ на нажатие)."""
    try:
        order = change_status(db, order_id, status)
    except StatusError as e:
        text, markup = order_reply(db, order_id)
        return text, markup, str(e)
    data = order.to_dict()
    toast = f"{data['number']}: {tg.status_line(status)}"
    return tg.order_card(data), tg.order_keyboard(data), toast


def link_reply(db: Session, token: str, chat_id: int) -> str:
    """Клиент пришёл по ссылке `/start <token>`: привязать Telegram к заказу, сказать статус."""
    order = link_telegram(db, token, chat_id)
    if order is None:
        return NOT_LINKED
    data = order.to_dict()
    status = tg.STATUS_LABELS.get(data["status"], data["status"])
    return (
        f"Подключили: статусы заказа <b>{data['number']}</b> будут приходить сюда.\n"
        f"Сейчас заказ в статусе «{status}». Страница заказа: {notify.order_url(data)}\n"
        "Отписаться — /stop."
    )


def stop_reply(db: Session, chat_id: int) -> str:
    n = unlink_telegram(db, chat_id)
    return "Отписали: статусы заказов сюда больше не придут." if n else "Подписок и так не было."


# --- хендлеры aiogram (подключаются в build_dispatcher) -------------------------


async def cmd_start(message: Message, command: CommandObject) -> None:
    """/start — подсказка владельцу; /start <token> — клиент подключает статусы заказа (B34)."""
    token = (command.args or "").strip()
    if token and message.from_user is not None:
        chat_id = message.chat.id
        await message.answer(await in_db(lambda db: link_reply(db, token, chat_id)))
        return
    await message.answer(HELP)


async def client_start(message: Message, command: CommandObject) -> None:
    """Чужой /start: с токеном — подключаем статусы, без — объясняем, что это за бот."""
    token = (command.args or "").strip()
    if not token:
        await message.answer(NOT_OWNER)
        return
    chat_id = message.chat.id
    await message.answer(await in_db(lambda db: link_reply(db, token, chat_id)))


async def cmd_stop(message: Message) -> None:
    chat_id = message.chat.id
    await message.answer(await in_db(lambda db: stop_reply(db, chat_id)))


async def cmd_orders(message: Message, command: CommandObject) -> None:
    active_only = (command.args or "").strip().lower() != "all"
    text, markup = await in_db(lambda db: orders_reply(db, active_only))
    await message.answer(text, reply_markup=kb(markup))


async def cmd_order(message: Message, command: CommandObject) -> None:
    raw = (command.args or "").strip().upper().replace("ТУЦ-", "").replace("#", "")
    if not raw.isdigit():
        await message.answer("Напишите номер: /order 12")
        return
    text, markup = await in_db(lambda db: order_reply(db, int(raw)))
    await message.answer(text, reply_markup=kb(markup))


async def on_button(query: CallbackQuery) -> None:
    kind, order_id, status = tg.parse_callback(query.data or "")
    message = query.message if isinstance(query.message, Message) else None

    if kind == "orders":
        text, markup = await in_db(lambda db: orders_reply(db, True))
        await query.answer()
        if message:
            await message.answer(text, reply_markup=kb(markup))
    elif kind == "order" and order_id is not None:
        text, markup = await in_db(lambda db: order_reply(db, order_id))
        await query.answer()
        if message:
            await message.answer(text, reply_markup=kb(markup))
    elif kind == "status" and order_id is not None and status is not None:
        text, markup, toast = await in_db(lambda db: status_reply(db, order_id, status))
        await query.answer(toast)
        if message:
            # Обновляем карточку на месте; если Telegram не даёт (старое сообщение) — шлём новую.
            try:
                await message.edit_text(text, reply_markup=kb(markup))
            except TelegramBadRequest as e:
                if "not modified" not in str(e):
                    await message.answer(text, reply_markup=kb(markup))
    else:
        await query.answer("Не понял кнопку.")


async def not_owner(message: Message) -> None:
    await message.answer(NOT_OWNER)


async def not_owner_button(query: CallbackQuery) -> None:
    await query.answer(NOT_OWNER, show_alert=True)


def build_dispatcher() -> Dispatcher:
    """Два роутера: владелец (команды и кнопки) и все остальные (вежливый отказ)."""
    owner = Router(name="owner")
    owner.message.filter(lambda m: is_owner(m.from_user.id if m.from_user else None))
    owner.callback_query.filter(lambda c: is_owner(c.from_user.id if c.from_user else None))
    owner.message.register(cmd_start, CommandStart())
    owner.message.register(cmd_start, Command("help"))
    owner.message.register(cmd_orders, Command("orders"))
    owner.message.register(cmd_order, Command("order"))
    owner.message.register(cmd_stop, Command("stop"))
    owner.callback_query.register(on_button)

    # Клиенты (B34): только подключение и отключение статусов, остальное — вежливый отказ.
    others = Router(name="others")
    others.message.register(client_start, CommandStart())
    others.message.register(cmd_stop, Command("stop"))
    others.message.register(not_owner)
    others.callback_query.register(not_owner_button)

    dp = Dispatcher()
    dp.include_router(owner)
    dp.include_router(others)
    return dp


def build_bot() -> Bot:
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if not settings.telegram_bot_token:
        log.error("TELEGRAM_BOT_TOKEN пуст — бот не запущен. Заполните .env (см. docs/STATUS.md).")
        return
    if owner_id() is None:
        log.error("TELEGRAM_OWNER_CHAT_ID пуст или не число — бот не запущен.")
        return
    bot = build_bot()
    dp = build_dispatcher()
    me = await bot.get_me()
    log.info("бот @%s запущен, владелец chat_id=%s", me.username, owner_id())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
