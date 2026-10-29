"""Уведомления клиенту о заказе (B34): письмо и/или сообщение в Telegram.

Когда владелец меняет статус (кнопка в боте B07, админка B09) или ЮKassa ставит «оплачен»
(B08), `orders.change_status` зовёт `status_changed(order)` — и клиент получает:
- письмо на e-mail из заказа (через `app/mailer.py`, нужен SMTP_HOST в .env);
- сообщение в Telegram, если он подключил бота: на странице заказа кнопка
  «Получать статусы в Telegram» ведёт на `https://t.me/<бот>?start=<token заказа>`,
  бот (`app/bot.py`) записывает chat_id клиента в `orders.telegram_chat_id`.
При оформлении заказа (`orders.create_order`) клиенту уходит письмо «заказ принят» со ссылкой
на страницу заказа — `order_created(order)`.

Тексты — здесь же, простым языком, без HTML в письме (как и код для входа, B32).
Отправка — в отдельном потоке (`IN_BACKGROUND`), чтобы владелец в боте и ЮKassa не ждали SMTP
(до 20 с). Ошибки почты и Telegram только пишутся в лог: статус в БД уже стоит.
Без e-mail и без Telegram у заказа уведомлений нет — клиенту остаётся страница /order/<token>.
"""

import logging
import threading

from app import telegram as tg
from app.config import settings
from app.mailer import mail_enabled, send_mail

log = logging.getLogger(__name__)

# В тестах ставят False — тогда отправка идёт сразу, в том же потоке.
IN_BACKGROUND = True

# Тема письма по статусу. {n} — номер заказа («BP-12»).
SUBJECTS = {
    "new": "Заказ {n} принят",
    "paid": "Заказ {n} оплачен",
    "printing": "Заказ {n} печатается",
    "ready": "Заказ {n} готов",
    "done": "Заказ {n} выдан",
    "cancelled": "Заказ {n} отменён",
}

# Первая фраза письма по статусу. Для «готов» текст зависит от способа получения.
BODIES = {
    "new": "Мы получили ваш заказ. Проверим модель и, если что-то не так, свяжемся по телефону.",
    "paid": "Оплата получена. Модель в очереди на печать — напишем, когда будет готово.",
    "printing": "Модель уже на принтере. Напишем, когда заказ будет готов.",
    "ready_pickup": "Заказ готов — можно забирать в студии. Адрес и часы работы: {contacts}",
    "ready_courier": "Заказ готов — передаём курьеру, он свяжется с вами по телефону.",
    "ready_cdek": "Заказ готов — отправляем СДЭК в выбранный пункт, номер отправления пришлём.",
    "done": "Заказ выдан. Спасибо, что печатаете с нами!",
    "cancelled": "Заказ отменён. Если это ошибка или остались вопросы — напишите нам: {contacts}",
}


def order_url(order: dict) -> str:
    return f"{settings.site_url}/order/{order['token']}"


def status_text(order: dict) -> tuple[str, str] | None:
    """(тема, текст) письма о текущем статусе заказа. None — для статуса текста нет."""
    status = order["status"]
    subject = SUBJECTS.get(status)
    if subject is None:
        return None
    key = status
    if status == "ready":
        by_delivery = {"pickup": "ready_pickup", "cdek": "ready_cdek"}
        key = by_delivery.get(order["delivery"], "ready_courier")
    body = BODIES[key].format(contacts=f"{settings.site_url}/contacts")
    lines = [f"Здравствуйте, {order['customer_name']}!", "", body]
    if status == "new":
        lines.append(_payment_hint(order))
    lines += [
        "",
        f"Заказ {order['number']}: {order['material']} × {order['qty']} шт, "
        f"{tg.fmt_money(order['total'])}.",
        f"Страница заказа: {order_url(order)}",
        "",
        "Студия 3D-печати BroPrint (БроПринт)",
    ]
    return subject.format(n=order["number"]), "\n".join(lines)


def _payment_hint(order: dict) -> str:
    """Как оплатить — в письме «заказ принят»."""
    if order.get("payment_method") == "invoice":
        return (
            "Оплата по счёту: счёт на оплату — на странице заказа (кнопка «Счёт на оплату»). "
            "Как только деньги поступят, заказ уйдёт в печать."
        )
    if settings.yookassa_shop_id and settings.yookassa_secret_key:
        return "Оплатить картой можно на странице заказа — после оплаты сразу ставим в печать."
    return "Менеджер подтвердит цену и срок и расскажет, как оплатить."


def telegram_text(subject: str, body: str) -> str:
    """То же письмо для Telegram: заголовок жирным, текст экранирован (parse_mode=HTML)."""
    return f"<b>{tg.esc(subject)}</b>\n{tg.esc(body)}"


def deliver(order: dict) -> dict:
    """Отправить уведомление о текущем статусе. → {"email": bool, "telegram": bool}
    (True — ушло; False — не было куда или не получилось)."""
    sent = {"email": False, "telegram": False}
    text = status_text(order)
    if text is None:
        return sent
    subject, body = text
    if order.get("email") and mail_enabled():
        sent["email"] = send_mail(order["email"], subject, body)
    if order.get("telegram_chat_id") and settings.telegram_bot_token:
        sent["telegram"] = tg.send_message(order["telegram_chat_id"], telegram_text(subject, body))
    log.info("уведомление клиенту по заказу %s (%s): %s", order["id"], order["status"], sent)
    return sent


def status_changed(order: dict) -> None:
    """Статус заказа поменялся — сообщить клиенту (в фоне). `order` — Order.to_dict()."""
    if order["status"] == "new":
        # «Принят» ставится при создании (письмо шлёт order_created) или возвратом из «отменён»;
        # во втором случае клиенту писать нечего — владелец свяжется сам.
        return
    _run(order)


def order_created(order: dict) -> None:
    """Заказ только что оформлен — письмо «принят» со ссылкой на страницу заказа."""
    _run(order)


def _run(order: dict) -> None:
    if not IN_BACKGROUND:
        deliver(order)
        return
    threading.Thread(target=deliver, args=(order,), daemon=True, name="notify-client").start()
