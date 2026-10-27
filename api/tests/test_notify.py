"""Статусы клиенту (B34): письма и Telegram при смене статуса, подключение бота к заказу."""

import asyncio

import httpx
import pytest
from aiogram.types import Update
from conftest import REPO_ROOT, box_stl
from test_telegram import STRANGER, RecordingSession, _msg_update, make_order

from app import bot, notify
from app import telegram as tg
from app.config import settings
from app.db import session_factory
from app.models import Order
from app.orders import change_status, link_telegram, unlink_telegram
from app.pricing import reload_pricing


@pytest.fixture
def session(db):
    s = session_factory()()
    yield s
    s.close()


@pytest.fixture
def mailbox(monkeypatch):
    """Вместо SMTP — список писем (кому, тема, текст)."""
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.ru")

    def fake_send(to, subject, text):
        sent.append((to, subject, text))
        return True

    monkeypatch.setattr(notify, "send_mail", fake_send)
    return sent


@pytest.fixture
def tg_box(monkeypatch):
    """Вместо Telegram — список сообщений (chat_id, текст)."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "42")

    def fake_send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(tg, "send_message", fake_send)
    return sent


@pytest.fixture
def pricing_file(monkeypatch):
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    yield
    reload_pricing()


# --- тексты -------------------------------------------------------------------


def test_status_text_by_status(session, monkeypatch):
    monkeypatch.setattr(settings, "site_url", "https://tuc.example")
    o = make_order(session, customer_name="Иван").to_dict()
    for status, subject in notify.SUBJECTS.items():
        text = notify.status_text(o | {"status": status})
        assert text is not None
        assert text[0] == subject.format(n="ТУЦ-1")
        assert text[1].startswith("Здравствуйте, Иван!")
        assert "PLA × 2 шт, 900 ₽" in text[1]
        assert f"https://tuc.example/order/{o['token']}" in text[1]
    assert notify.status_text(o | {"status": "unknown"}) is None


def test_ready_text_depends_on_delivery(session, monkeypatch):
    monkeypatch.setattr(settings, "site_url", "https://tuc.example")
    pickup = make_order(session, delivery="pickup").to_dict() | {"status": "ready"}
    courier = make_order(session, delivery="courier_moscow", address="Тверская, 1").to_dict()
    assert "забирать в студии" in notify.status_text(pickup)[1]
    assert "https://tuc.example/contacts" in notify.status_text(pickup)[1]
    assert "курьеру" in notify.status_text(courier | {"status": "ready"})[1]


def test_new_text_explains_payment(session, monkeypatch):
    o = make_order(session).to_dict()
    assert "подтвердит цену" in notify.status_text(o)[1]  # ЮKassa не настроена
    monkeypatch.setattr(settings, "yookassa_shop_id", "shop")
    monkeypatch.setattr(settings, "yookassa_secret_key", "key")
    assert "Оплатить картой" in notify.status_text(o)[1]
    invoice = make_order(session, payment_method="invoice", company_name="ООО Ромашка").to_dict()
    assert "по счёту" in notify.status_text(invoice)[1]


def test_telegram_text_escapes():
    text = notify.telegram_text("Заказ <1>", "a & b")
    assert text == "<b>Заказ &lt;1&gt;</b>\na &amp; b"


# --- доставка -----------------------------------------------------------------


def test_deliver_email_and_telegram(session, mailbox, tg_box):
    o = make_order(session, email="ivan@example.ru", telegram_chat_id="777", status="printing")
    assert notify.deliver(o.to_dict()) == {"email": True, "telegram": True}
    assert mailbox[0][0] == "ivan@example.ru" and mailbox[0][1] == "Заказ ТУЦ-1 печатается"
    assert tg_box[0][0] == "777" and tg_box[0][1].startswith("<b>Заказ ТУЦ-1 печатается</b>")


def test_deliver_nowhere(session, mailbox, tg_box):
    """Без e-mail и без Telegram — тихо ничего; без SMTP письмо не шлём."""
    o = make_order(session, status="ready").to_dict()
    assert notify.deliver(o) == {"email": False, "telegram": False}
    assert mailbox == [] and tg_box == []


def test_deliver_without_smtp_skips_email(session, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    called = []
    monkeypatch.setattr(notify, "send_mail", lambda *a: called.append(a) or True)
    o = make_order(session, email="ivan@example.ru", status="ready").to_dict()
    assert notify.deliver(o)["email"] is False and called == []


def test_change_status_notifies_client(session, mailbox):
    """Кнопка в боте / админка / ЮKassa → change_status → клиенту письмо о новом статусе."""
    o = make_order(session, email="ivan@example.ru")
    change_status(session, o.id, "paid")
    change_status(session, o.id, "printing")
    assert [m[1] for m in mailbox] == ["Заказ ТУЦ-1 оплачен", "Заказ ТУЦ-1 печатается"]
    change_status(session, o.id, "ready", notify_client=False)
    assert len(mailbox) == 2
    # возврат в «принят» (из отменённого) — без письма
    change_status(session, o.id, "cancelled")
    change_status(session, o.id, "new")
    assert [m[1] for m in mailbox][-1] == "Заказ ТУЦ-1 отменён"


def test_background_thread_delivers(session, mailbox, monkeypatch):
    """В проде отправка идёт в отдельном потоке — владелец в боте не ждёт SMTP."""
    import threading

    monkeypatch.setattr(notify, "IN_BACKGROUND", True)
    done = threading.Event()
    real = notify.deliver

    def deliver_and_signal(order):
        real(order)
        done.set()

    monkeypatch.setattr(notify, "deliver", deliver_and_signal)
    o = make_order(session, email="ivan@example.ru", status="ready").to_dict()
    notify.status_changed(o)
    assert done.wait(5) and mailbox[0][1] == "Заказ ТУЦ-1 готов"


# --- API: письмо «принят» и блок notifications -----------------------------------


def _order(client, **extra) -> dict:
    r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    upload_id = r.json()["id"]
    client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    q = client.post(
        f"/api/v1/uploads/{upload_id}/quote",
        json={"material": "PLA", "qty": 1, "delivery": "pickup"},
    ).json()
    body = {"quote_id": q["id"], "name": "Иван", "phone": "9991234567", "consent": True} | extra
    o = client.post("/api/v1/orders", json=body)
    assert o.status_code == 201, o.text
    return o.json()


def test_create_order_sends_confirmation(client, pricing_file, fake_slicer, mailbox):
    order = _order(client, email="ivan@example.ru")
    assert len(mailbox) == 1
    to, subject, text = mailbox[0]
    assert to == "ivan@example.ru" and subject == "Заказ ТУЦ-1 принят"
    assert f"/order/{order['token']}" in text
    assert order["notifications"] == {
        "email": "ivan@example.ru",
        "telegram_linked": False,
        "telegram_link": None,  # бот не настроен
    }


def test_create_order_without_email_no_letter(client, pricing_file, fake_slicer, mailbox):
    order = _order(client)
    assert mailbox == [] and order["notifications"]["email"] is None


def test_notifications_telegram_link(client, pricing_file, fake_slicer, monkeypatch, db):
    """С токеном бота в ответе заказа — ссылка t.me/<бот>?start=<token>; имя бота — из getMe."""
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return httpx.Response(200, json={"ok": True, "result": {"username": "tuc_print_bot"}})

    monkeypatch.setattr(tg.httpx, "get", fake_get)
    order = _order(client)
    n = order["notifications"]
    assert n["telegram_link"] == f"https://t.me/tuc_print_bot?start={order['token']}"
    assert n["telegram_linked"] is False
    client.get(f"/api/v1/orders/{order['token']}")
    assert len(calls) == 1  # getMe спрашиваем один раз

    # клиент подключил бота — ссылки больше нет, подключение видно
    s = session_factory()()
    assert link_telegram(s, order["token"], 777) is not None
    s.close()
    n = client.get(f"/api/v1/orders/{order['token']}").json()["notifications"]
    assert n == {"email": None, "telegram_linked": True, "telegram_link": None}


def test_bot_username_failure_is_cached(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    calls = []

    def fail(url, timeout=None):
        calls.append(url)
        raise httpx.ConnectError("нет сети")

    monkeypatch.setattr(tg.httpx, "get", fail)
    assert tg.bot_username() is None
    assert tg.bot_username() is None
    assert len(calls) == 1  # повтор не раньше чем через BOT_USERNAME_RETRY_S
    monkeypatch.setattr(tg.httpx, "get", lambda url, timeout=None: httpx.Response(500, text="bad"))
    tg.forget_bot_username()
    assert tg.bot_username() is None
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert tg.bot_username() is None


def test_bot_username_asks_on_fresh_machine(monkeypatch):
    """Сразу после загрузки системы time.monotonic() меньше 5 минут (так на CI). Кэш «ещё не
    спрашивали» не должен принимать это за «только что спрашивали» — getMe должен уйти."""
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(tg.time, "monotonic", lambda: 42.0)  # машина работает 42 секунды
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return httpx.Response(200, json={"ok": True, "result": {"username": "tuc_print_bot"}})

    monkeypatch.setattr(tg.httpx, "get", fake_get)
    tg.forget_bot_username()
    assert tg.bot_username() == "tuc_print_bot"
    assert len(calls) == 1


# --- бот: /start <token> и /stop --------------------------------------------------


def test_link_and_unlink(session):
    o = make_order(session)
    assert link_telegram(session, "не токен", 7) is None
    assert link_telegram(session, "f" * 32, 7) is None
    assert link_telegram(session, o.token, 7).telegram_chat_id == "7"
    assert unlink_telegram(session, 7) == 1 and unlink_telegram(session, 7) == 0
    session.expire_all()
    assert session.get(Order, o.id).telegram_chat_id is None


def test_bot_client_subscribes(session, monkeypatch, mailbox, tg_box):
    monkeypatch.setattr(settings, "site_url", "https://tuc.example")
    o = make_order(session, email="ivan@example.ru")
    tg_session = RecordingSession()
    aiobot = bot.Bot(token="123:ABC", session=tg_session)
    dp = bot.build_dispatcher()

    async def send(update: Update):
        tg_session.calls.clear()
        await dp.feed_update(aiobot, update)
        return tg_session.calls

    async def scenario():
        (m,) = await send(_msg_update("/start", STRANGER))
        assert m.text == bot.NOT_OWNER

        (m,) = await send(_msg_update("/start " + "f" * 32, STRANGER))
        assert m.text == bot.NOT_LINKED

        (m,) = await send(_msg_update(f"/start {o.token}", STRANGER))
        assert "ТУЦ-1" in m.text and "«принят»" in m.text and f"/order/{o.token}" in m.text
        session.expire_all()
        assert session.get(Order, o.id).telegram_chat_id == str(STRANGER.id)

        # владелец ставит статус — клиенту уходит и письмо, и сообщение в Telegram
        bot.status_reply(session, o.id, "printing")
        assert mailbox[-1][1] == "Заказ ТУЦ-1 печатается"
        assert tg_box[-1] == (
            str(STRANGER.id),
            notify.telegram_text(*notify.status_text(session.get(Order, o.id).to_dict())),
        )

        (m,) = await send(_msg_update("/stop", STRANGER))
        assert m.text.startswith("Отписали")
        session.expire_all()
        assert session.get(Order, o.id).telegram_chat_id is None
        (m,) = await send(_msg_update("/stop", STRANGER))
        assert m.text == "Подписок и так не было."

        # остальное клиентам по-прежнему недоступно
        (m,) = await send(_msg_update("/orders", STRANGER))
        assert m.text == bot.NOT_OWNER

        # владелец тоже может подключить статусы своего тестового заказа
        (m,) = await send(_msg_update(f"/start {o.token}"))
        assert m.text.startswith("Подключили")

    asyncio.run(scenario())


def test_owner_card_shows_client_channels(session):
    o = make_order(session, email="ivan@example.ru", telegram_chat_id="7").to_dict()
    assert "Статусы клиенту: Telegram и e-mail" in tg.order_card(o)
    assert "Статусы клиенту" not in tg.order_card(make_order(session).to_dict())
