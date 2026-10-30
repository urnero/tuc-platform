"""Telegram (B07): тексты и кнопки, уведомление о заказе, смена статуса, бот."""

import asyncio
from datetime import UTC, datetime

import pytest
from aiogram.client.session.base import BaseSession
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User
from conftest import REPO_ROOT, box_stl
from sqlalchemy.orm import Session

from app import bot
from app import telegram as tg
from app.config import settings
from app.db import session_factory
from app.models import ORDER_STATUSES, Order
from app.orders import StatusError, change_status, list_orders
from app.pricing import reload_pricing

QUOTE = {
    "id": "a" * 32 + "-abcdef",
    "material_g": 50.0,
    "print_time_s": 7200,
    "total": 900,
}


def make_order(db: Session, **kw) -> Order:
    """Заказ прямо в БД, без загрузки и слайсера."""
    fields = dict(
        token=kw.pop("token", "%032x" % (db.query(Order).count() + 1)),
        customer_name="Иван <b>",
        phone="+79991234567",
        email=None,
        delivery="pickup",
        address=None,
        comment=None,
        upload_id="a" * 32,
        quote_id=QUOTE["id"],
        original_name="box.stl",
        material="PLA",
        supports=False,
        qty=2,
        postprocess="none",
        total=900,
        currency="RUB",
        quote=QUOTE,
    )
    fields.update(kw)
    order = Order(**fields)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@pytest.fixture
def session(db):
    s = session_factory()()
    yield s
    s.close()


# --- тексты и кнопки -----------------------------------------------------------


def test_order_card_escapes_and_links(session, monkeypatch):
    monkeypatch.setattr(settings, "site_url", "https://tuc.example")
    o = make_order(session, comment="срочно & <script>", address=None).to_dict()
    text = tg.order_card(o)
    assert text.startswith("<b>Заказ BP-1</b> · 900 ₽")
    assert "Иван &lt;b&gt;" in text  # имя клиента экранировано
    assert "срочно &amp; &lt;script&gt;" in text
    assert "PLA × 2 шт" in text
    assert "Печать: ~4.0 ч, 100 г" in text  # 2 изделия по 2 ч и 50 г
    assert "самовывоз" in text
    page = f"https://tuc.example/order/{o['token']}"
    assert text.endswith(f'<a href="{page}">Страница заказа</a>')

    header = tg.order_card(o, header="🆕 Новый заказ BP-1")
    assert header.startswith("<b>🆕 Новый заказ BP-1</b>")


def test_order_card_links_admin_and_drive(session, monkeypatch):
    """B48: под карточкой — ссылки на страницу заказа, админку (если включена) и папку Drive."""
    monkeypatch.setattr(settings, "site_url", "https://tuc.example/")
    o = make_order(session).to_dict()
    monkeypatch.setattr(settings, "admin_password", "")
    assert "Админка" not in tg.order_card(o)  # админка выключена — ссылка вела бы в 503
    monkeypatch.setattr(settings, "admin_password", "secret")
    o["drive_folder_url"] = "https://drive.google.com/drive/folders/abc?x=1&y=2"
    last = tg.order_card(o).splitlines()[-1]
    assert '<a href="https://tuc.example/admin/orders/1">Админка</a>' in last
    drive = "https://drive.google.com/drive/folders/abc?x=1&amp;y=2"
    assert f'<a href="{drive}">Файлы в Drive</a>' in last


def test_order_card_courier_address(session):
    o = make_order(session, delivery="courier_moscow", address="Тверская, 1").to_dict()
    assert "курьер по Москве — Тверская, 1" in tg.order_card(o)


def test_order_card_decor_line(session):
    """Раскраска по частям (B31) / тиснение (B30) — строка «Оформление» из снимка расчёта."""
    quote = QUOTE | {"decor": "Деталь 1 — красный, Деталь 2 — <синий>"}
    o = make_order(session, quote=quote).to_dict()
    assert "Оформление: Деталь 1 — красный, Деталь 2 — &lt;синий&gt;" in tg.order_card(o)
    assert "Оформление" not in tg.order_card(make_order(session).to_dict())


def test_fmt_money():
    assert tg.fmt_money(900) == "900 ₽"
    assert tg.fmt_money(12345.4) == "12 345 ₽"


def test_fmt_msk():
    assert tg.fmt_msk("2026-10-19T21:41:00+00:00") == "20.10 00:41"
    assert tg.fmt_msk(None) == ""


@pytest.mark.parametrize(
    "status, expected",
    [
        ("new", ["status:7:paid", "status:7:printing", "status:7:cancelled"]),
        ("printing", ["status:7:ready", "status:7:cancelled"]),
        ("done", []),
        ("cancelled", ["status:7:new"]),
    ],
)
def test_order_keyboard(status, expected):
    markup = tg.order_keyboard({"id": 7, "status": status})
    rows = markup["inline_keyboard"]
    data = [b["callback_data"] for row in rows[:-1] for b in row]
    assert data == expected
    assert all(len(row) <= 2 for row in rows[:-1])
    assert rows[-1] == [{"text": "📋 Активные заказы", "callback_data": "orders"}]


def test_next_statuses_cover_all():
    assert set(tg.NEXT_STATUSES) == set(ORDER_STATUSES)
    for s, nxt in tg.NEXT_STATUSES.items():
        assert s not in nxt and set(nxt) <= set(ORDER_STATUSES)
    assert set(tg.STATUS_LABELS) == set(ORDER_STATUSES) == set(tg.STATUS_ICONS)


def test_orders_list(session):
    text, markup = tg.orders_list([])
    assert "Пока пусто" in text and markup == {"inline_keyboard": []}

    orders = [make_order(session).to_dict() for _ in range(5)]
    text, markup = tg.orders_list(orders, title="Активные заказы")
    assert text.startswith("<b>Активные заказы</b>")
    assert "<b>BP-3</b> · Иван &lt;b&gt; · PLA × 2 · 900 ₽" in text
    buttons = [b for row in markup["inline_keyboard"] for b in row]
    assert [b["callback_data"] for b in buttons] == [f"order:{o['id']}" for o in orders]
    assert [len(r) for r in markup["inline_keyboard"]] == [4, 1]


@pytest.mark.parametrize(
    "data, expected",
    [
        ("orders", ("orders", None, None)),
        ("order:12", ("order", 12, None)),
        ("status:12:paid", ("status", 12, "paid")),
        ("status:12:nope", ("?", None, None)),
        ("status:x:paid", ("?", None, None)),
        ("order:12:extra", ("?", None, None)),
        ("", ("?", None, None)),
    ],
)
def test_parse_callback(data, expected):
    assert tg.parse_callback(data) == expected


# --- отправка ----------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def tg_calls(monkeypatch):
    """Вместо настоящего Telegram — запоминаем, что отправили."""
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return FakeResponse()

    monkeypatch.setattr(tg.httpx, "post", fake_post)
    return calls


def test_notify_disabled_without_token(monkeypatch, tg_calls):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "123")
    assert tg.telegram_enabled() is False
    assert tg.notify_owner_new_order({"id": 1}) is False
    assert tg_calls == []


def test_notify_owner_new_order(monkeypatch, tg_calls, session):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "42")
    order = make_order(session).to_dict()
    assert tg.notify_owner_new_order(order) is True
    url, payload = tg_calls[0]
    assert url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert payload["chat_id"] == "42"
    assert payload["parse_mode"] == "HTML"
    assert "🆕 Новый заказ BP-1" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "status:1:paid"


def test_send_message_errors_do_not_raise(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(tg.httpx, "post", lambda *a, **k: FakeResponse(401, "Unauthorized"))
    assert tg.send_message("42", "hi") is False

    def boom(*a, **k):
        raise tg.httpx.ConnectError("no network")

    monkeypatch.setattr(tg.httpx, "post", boom)
    assert tg.send_message("42", "hi") is False


def test_send_message_retries_network_and_5xx(monkeypatch):
    """B48: обрыв сети и 5xx — повторяем (1 с, 3 с), на третий раз прошло."""
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    sleeps: list[float] = []
    monkeypatch.setattr(tg.time, "sleep", sleeps.append)
    answers = [tg.httpx.ConnectError("no network"), FakeResponse(502, "Bad"), FakeResponse()]

    def flaky(*a, **k):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(tg.httpx, "post", flaky)
    assert tg.send_message("42", "hi") is True
    assert sleeps == [1, 3] and answers == []


def test_send_message_gives_up_and_skips_client_errors(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    sleeps: list[float] = []
    monkeypatch.setattr(tg.time, "sleep", sleeps.append)
    calls = []

    def down(*a, **k):
        calls.append(1)
        raise tg.httpx.ConnectError("no network")

    monkeypatch.setattr(tg.httpx, "post", down)
    assert tg.send_message("42", "hi") is False
    assert len(calls) == 3 and sleeps == [1, 3]  # три попытки и сдались

    # 400/401/403 — ошибка в запросе или токене: повтор не поможет
    calls.clear(), sleeps.clear()
    monkeypatch.setattr(tg.httpx, "post", lambda *a, **k: calls.append(1) or FakeResponse(403))
    assert tg.send_message("42", "hi") is False
    assert len(calls) == 1 and sleeps == []


def test_send_message_429_waits_retry_after(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    sleeps: list[float] = []
    monkeypatch.setattr(tg.time, "sleep", sleeps.append)

    class TooMany(FakeResponse):
        def json(self):
            return {"ok": False, "parameters": {"retry_after": 60}}

    answers = [TooMany(429, "Too Many Requests"), FakeResponse()]
    monkeypatch.setattr(tg.httpx, "post", lambda *a, **k: answers.pop(0))
    assert tg.send_message("42", "hi") is True
    assert sleeps == [tg.MAX_RETRY_AFTER_S]  # просили 60 с — ждём не больше 10


def test_today_start_is_moscow_midnight():
    # 21:30 UTC 28.10 = 00:30 МСК 29.10 → начало дня 29.10 по Москве = 21:00 UTC 28.10
    now = datetime(2026, 10, 28, 21, 30, tzinfo=UTC)
    assert bot.today_start_utc(now) == datetime(2026, 10, 28, 21, 0, tzinfo=UTC)
    now = datetime(2026, 10, 28, 20, 59, tzinfo=UTC)  # 23:59 МСК 28.10
    assert bot.today_start_utc(now) == datetime(2026, 10, 27, 21, 0, tzinfo=UTC)


def test_today_reply(session):
    make_order(session)
    make_order(session, status="cancelled")
    old = make_order(session, status="printing")
    old.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    session.commit()
    text, markup = bot.today_reply(session)
    # сегодня два заказа, отменённый в сумму не входит; в работе — новый и печатающийся
    assert text.startswith("<b>Сегодня: 2 заказ(ов) на 900 ₽ · в работе 2</b>")
    assert [b["callback_data"] for row in markup["inline_keyboard"] for b in row] == [
        "order:2",
        "order:1",
    ]


def test_create_order_notifies_owner(client, fake_slicer, monkeypatch):
    """POST /orders → после ответа уходит уведомление с данными заказа."""
    from app import orders as orders_module

    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    sent: list[dict] = []
    monkeypatch.setattr(orders_module, "notify_owner_new_order", lambda o: sent.append(o))

    r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    upload_id = r.json()["id"]
    client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    quote = client.post(
        f"/api/v1/uploads/{upload_id}/quote", json={"material": "PLA", "qty": 1}
    ).json()
    r = client.post(
        "/api/v1/orders",
        json={"quote_id": quote["id"], "name": "Иван", "phone": "9991234567", "consent": True},
    )
    assert r.status_code == 201, r.text
    assert len(sent) == 1
    assert sent[0]["number"] == "BP-1" and sent[0]["token"] == r.json()["token"]
    reload_pricing()  # чтобы кэш прайса не утёк в другие тесты


# --- смена статуса -------------------------------------------------------------


def test_change_status(session):
    make_order(session)
    o = change_status(session, 1, "printing")
    assert o.status == "printing"
    assert session.get(Order, 1).status == "printing"

    with pytest.raises(StatusError, match="уже"):
        change_status(session, 1, "printing")
    with pytest.raises(StatusError, match="Неизвестный"):
        change_status(session, 1, "shipped")
    with pytest.raises(StatusError, match="не найден"):
        change_status(session, 99, "paid")


def test_list_orders_active_first_new_on_top(session):
    for st in ["new", "done", "printing", "cancelled", "ready"]:
        make_order(session, status=st)
    active = [o.id for o in list_orders(session, active_only=True)]
    assert active == [5, 3, 1]
    everything = [o.id for o in list_orders(session, active_only=False)]
    assert everything == [5, 4, 3, 2, 1]
    assert len(list_orders(session, active_only=False, limit=2)) == 2


# --- бот ---------------------------------------------------------------------


def test_is_owner(monkeypatch):
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "42")
    assert bot.is_owner(42) and not bot.is_owner(43) and not bot.is_owner(None)
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "")
    assert bot.owner_id() is None and not bot.is_owner(42)
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "abc")
    assert bot.owner_id() is None


def test_bot_replies(session):
    text, markup = bot.orders_reply(session)
    assert "Пока пусто" in text

    make_order(session)
    make_order(session, status="done")
    text, markup = bot.orders_reply(session, active_only=True)
    assert "BP-1" in text and "BP-2" not in text
    text, markup = bot.orders_reply(session, active_only=False)
    assert "BP-1" in text and "BP-2" in text and "Последние 20" in text

    text, markup = bot.order_reply(session, 1)
    assert "Заказ BP-1" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == "status:1:paid"
    text, markup = bot.order_reply(session, 9)
    assert "не найден" in text and markup == {"inline_keyboard": []}

    text, markup, toast = bot.status_reply(session, 1, "paid")
    assert "Статус: 💰 оплачен" in text and toast == "BP-1: 💰 оплачен"
    assert markup["inline_keyboard"][0][0]["callback_data"] == "status:1:printing"
    text, markup, toast = bot.status_reply(session, 1, "paid")  # повторно — ошибка, карточка та же
    assert "уже в статусе «оплачен»" in toast and "Статус: 💰 оплачен" in text

    # словарь кнопок превращается в объект aiogram без потерь
    kb = bot.kb(markup)
    assert kb.inline_keyboard[0][0].callback_data == "status:1:printing"


def test_bot_dispatcher_builds(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    dp = bot.build_dispatcher()
    assert [r.name for r in dp.sub_routers] == ["owner", "others"]
    assert bot.build_bot().token == "123:ABC"


# --- бот целиком: обновления Telegram → ответы, без сети ---------------------------


class RecordingSession(BaseSession):
    """Подменяет сеть aiogram: запоминает вызовы Bot API и отвечает «как Telegram»."""

    def __init__(self):
        super().__init__()
        self.calls: list = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if type(method).__name__ in ("SendMessage", "EditMessageText"):
            return Message(
                message_id=len(self.calls),
                date=datetime.now(UTC),
                chat=Chat(id=42, type="private"),
                text=method.text,
            )
        return True

    async def stream_content(self, *args, **kwargs):
        yield b""


OWNER = User(id=42, is_bot=False, first_name="Girg")
STRANGER = User(id=7, is_bot=False, first_name="Кто-то")


def _msg_update(text: str, user: User = OWNER) -> Update:
    entities = None
    if text.startswith("/"):
        entities = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))]
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=user.id, type="private"),
            from_user=user,
            text=text,
            entities=entities,
        ),
    )


def _button_update(data: str, user: User = OWNER) -> Update:
    card = Message(
        message_id=5,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=User(id=999, is_bot=True, first_name="bot"),
        text="карточка",
    )
    return Update(
        update_id=2,
        callback_query=CallbackQuery(
            id="1", from_user=user, chat_instance="x", data=data, message=card
        ),
    )


def _buttons(method) -> list[str]:
    markup = getattr(method, "reply_markup", None)
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


def test_bot_end_to_end(session, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "42")
    make_order(session)
    make_order(session, status="done")
    tg_session = RecordingSession()
    aiobot = bot.Bot(token="123:ABC", session=tg_session)
    dp = bot.build_dispatcher()

    async def send(update: Update):
        tg_session.calls.clear()
        await dp.feed_update(aiobot, update)
        return tg_session.calls

    async def scenario():
        (m,) = await send(_msg_update("/start"))
        assert "Бот студии BroPrint" in m.text

        (m,) = await send(_msg_update("/orders"))
        assert "BP-1" in m.text and "BP-2" not in m.text and _buttons(m) == ["order:1"]

        (m,) = await send(_msg_update("/orders all"))
        assert _buttons(m) == ["order:2", "order:1"]

        (m,) = await send(_msg_update("/order BP-1"))
        assert m.text.startswith("<b>Заказ BP-1</b>")
        assert _buttons(m) == ["status:1:paid", "status:1:printing", "status:1:cancelled", "orders"]

        (m,) = await send(_msg_update("/today"))
        assert m.text.startswith("<b>Сегодня: 2 заказ(ов)")
        assert _buttons(m) == ["order:2", "order:1"]

        (m,) = await send(_msg_update("/help"))
        assert "/today" in m.text

        (m,) = await send(_msg_update("/order abc"))
        assert "/order 12" in m.text

        answer, m = await send(_button_update("order:1"))
        assert type(m).__name__ == "SendMessage" and "BP-1" in m.text

        # кнопка статуса: запись в БД, карточка редактируется на месте
        answer, edit = await send(_button_update("status:1:paid"))
        assert answer.text == "BP-1: 💰 оплачен"
        assert type(edit).__name__ == "EditMessageText"
        assert "Статус: 💰 оплачен" in edit.text
        assert _buttons(edit) == ["status:1:printing", "status:1:cancelled", "orders"]
        session.expire_all()
        assert session.get(Order, 1).status == "paid"

        answer, _ = await send(_button_update("status:1:paid"))
        assert "уже в статусе «оплачен»" in answer.text

        (answer,) = await send(_button_update("мусор"))
        assert answer.text == "Не понял кнопку."

        # чужие — отказ, статус не меняется
        (m,) = await send(_msg_update("/orders", STRANGER))
        assert m.text == bot.NOT_OWNER
        (answer,) = await send(_button_update("status:1:done", STRANGER))
        assert answer.text == bot.NOT_OWNER and answer.show_alert is True
        session.expire_all()
        assert session.get(Order, 1).status == "paid"

    asyncio.run(scenario())


def test_bot_setup_commands(monkeypatch):
    """B48: меню команд — владельцу все, остальным только /stop; сбой сети не роняет бота."""
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "42")
    tg_session = RecordingSession()
    aiobot = bot.Bot(token="123:ABC", session=tg_session)
    asyncio.run(bot.setup_commands(aiobot))
    client_menu, owner_menu = tg_session.calls
    assert [c.command for c in client_menu.commands] == ["stop"]
    assert owner_menu.scope.chat_id == 42
    assert [c.command for c in owner_menu.commands] == ["orders", "today", "order", "help"]

    class Down(RecordingSession):
        async def make_request(self, bot, method, timeout=None):
            raise OSError("no network")

    asyncio.run(bot.setup_commands(bot.Bot(token="123:ABC", session=Down())))  # без исключения
