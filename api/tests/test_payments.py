"""Оплата ЮKassa (B08): создание платежа, возврат клиента, вебхук, идемпотентность, Telegram."""

import json

import httpx
import pytest
from conftest import REPO_ROOT, box_stl
from fastapi.testclient import TestClient

from app import payments, telegram
from app.config import settings
from app.main import app
from app.models import Order, Payment
from app.pricing import reload_pricing


@pytest.fixture
def pricing_file(monkeypatch):
    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    yield
    reload_pricing()


class FakeYooKassa:
    """Поддельная ЮKassa: хранит платежи в памяти, отвечает на POST /payments и GET /payments/{id}.

    Тест сам «проводит» оплату: fake.pay(id) или fake.cancel(id) — как если бы клиент
    заплатил на форме. Запросы с неверной авторизацией получают 401.
    """

    def __init__(self):
        self.payments: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []
        self.by_key: dict[str, str] = {}  # Idempotence-Key → id платежа

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        auth = request.headers.get("authorization", "")
        if auth != "Basic " + _basic("shop-1", "test_key"):
            return httpx.Response(401, json={"description": "Unauthorized"})
        path = request.url.path
        if request.method == "POST" and path == "/v3/payments":
            key = request.headers["idempotence-key"]
            if key in self.by_key:
                return httpx.Response(200, json=self.payments[self.by_key[key]])
            body = json.loads(request.content)
            pid = f"2d{len(self.payments) + 1:04d}-000f-5000-8000-1d2c3a4b5e6f"
            obj = {
                "id": pid,
                "status": "pending",
                "paid": False,
                "amount": body["amount"],
                "confirmation": {
                    "type": "redirect",
                    "confirmation_url": f"https://yoomoney.ru/checkout/payments/v2/contract?orderId={pid}",
                },
                "description": body.get("description"),
                "metadata": body.get("metadata", {}),
                "test": True,
            }
            self.payments[pid] = obj
            self.by_key[key] = pid
            return httpx.Response(200, json=obj)
        if request.method == "GET" and path.startswith("/v3/payments/"):
            pid = path.rsplit("/", 1)[1]
            if pid not in self.payments:
                return httpx.Response(404, json={"description": "Not found"})
            return httpx.Response(200, json=self.payments[pid])
        return httpx.Response(404, json={"description": f"no route {path}"})

    def pay(self, pid: str) -> dict:
        obj = self.payments[pid]
        obj.update(status="succeeded", paid=True, captured_at="2026-10-20T01:02:03.000Z")
        obj.pop("confirmation", None)
        return obj

    def cancel(self, pid: str) -> dict:
        obj = self.payments[pid]
        obj.update(status="canceled", paid=False)
        obj.pop("confirmation", None)
        return obj

    def webhook_body(self, pid: str, event: str | None = None) -> dict:
        obj = self.payments[pid]
        return {"type": "notification", "event": event or f"payment.{obj['status']}", "object": obj}


def _basic(user: str, password: str) -> str:
    import base64

    return base64.b64encode(f"{user}:{password}".encode()).decode()


@pytest.fixture
def yookassa(monkeypatch):
    """Включает оплату (ключи тестового магазина) и подставляет поддельную ЮKassa."""
    fake = FakeYooKassa()
    monkeypatch.setattr(settings, "yookassa_shop_id", "shop-1")
    monkeypatch.setattr(settings, "yookassa_secret_key", "test_key")
    monkeypatch.setattr(settings, "yookassa_api_url", "https://api.yookassa.ru/v3")
    monkeypatch.setattr(settings, "site_url", "https://tuc.example")
    monkeypatch.setattr(payments, "TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


@pytest.fixture
def tg_sent(monkeypatch):
    """Ловим сообщения владельцу вместо настоящего Telegram."""
    sent: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "42")

    def fake_send(chat_id, text, reply_markup=None):
        sent.append((text, reply_markup))
        return True

    monkeypatch.setattr(telegram, "send_message", fake_send)
    return sent


def _order(client, qty=1) -> dict:
    """Загрузка → слайсинг (подделка) → цена → заказ. Возвращает заказ с token."""
    r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    upload_id = r.json()["id"]
    client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    q = client.post(
        f"/api/v1/uploads/{upload_id}/quote",
        json={"material": "PLA", "qty": qty, "delivery": "pickup"},
    ).json()
    o = client.post(
        "/api/v1/orders",
        json={"quote_id": q["id"], "name": "Иван", "phone": "9991234567", "consent": True},
    )
    assert o.status_code == 201, o.text
    return o.json()


# --- без ключей -----------------------------------------------------------------


def test_payment_disabled_without_keys(client, pricing_file, fake_slicer):
    order = _order(client)
    assert order["payment"] == {
        "enabled": False,
        "status": None,
        "confirmation_url": None,
        "paid_at": None,
    }
    r = client.post(f"/api/v1/orders/{order['token']}/payment")
    assert r.status_code == 503
    assert client.post("/api/v1/payments/yookassa/webhook", json={}).status_code == 503


# --- тело запроса в ЮKassa ---------------------------------------------------------


def test_build_payment_request(monkeypatch):
    monkeypatch.setattr(settings, "site_url", "https://tuc.example")
    monkeypatch.setattr(settings, "yookassa_vat_code", "")
    order = Order(
        id=7, token="a" * 32, total=1234, currency="RUB", material="PETG", qty=3,
        phone="+79991234567", email="a@b.ru",
    )  # fmt: skip
    body = payments.build_payment_request(order)
    assert body["amount"] == {"value": "1234.00", "currency": "RUB"}
    assert body["capture"] is True
    assert body["confirmation"] == {
        "type": "redirect",
        "return_url": "https://tuc.example/order/" + "a" * 32 + "?payment=check",
    }
    assert "ТУЦ-7" in body["description"] and "PETG × 3" in body["description"]
    assert body["metadata"] == {"order_id": "7"}
    assert "receipt" not in body

    # с кодом НДС появляется чек 54-ФЗ на всю сумму
    monkeypatch.setattr(settings, "yookassa_vat_code", "1")
    receipt = payments.build_payment_request(order)["receipt"]
    assert receipt["customer"] == {"phone": "79991234567", "email": "a@b.ru"}
    assert receipt["items"][0]["amount"] == {"value": "1234.00", "currency": "RUB"}
    assert receipt["items"][0]["vat_code"] == 1


def test_fmt_amount():
    assert payments.fmt_amount(500) == "500.00"
    assert payments.fmt_amount(3353) == "3353.00"


# --- полный путь: кнопка → форма → возврат клиента ------------------------------------


def test_pay_via_return(client, pricing_file, fake_slicer, yookassa, tg_sent, db):
    order = _order(client, qty=2)
    assert order["payment"]["enabled"] is True
    token = order["token"]

    r = client.post(f"/api/v1/orders/{token}/payment")
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["confirmation_url"].startswith("https://yoomoney.ru/checkout/")
    assert p["payment"]["status"] == "pending"
    assert p["payment"]["amount"] == order["total"]
    yk_id = p["payment"]["yookassa_id"]
    # ЮKassa получила сумму заказа и наш ключ идемпотентности
    sent = json.loads(yookassa.requests[0].content)
    assert sent["amount"]["value"] == f"{order['total']}.00"
    assert yookassa.requests[0].headers["idempotence-key"]

    # страница статуса видит начатый платёж и ссылку на форму
    g = client.get(f"/api/v1/orders/{token}").json()
    assert g["payment"]["status"] == "pending"
    assert g["payment"]["confirmation_url"] == p["confirmation_url"]
    assert g["status"] == "new"

    # повторное нажатие «Оплатить», пока форма открыта, — тот же платёж, без нового в ЮKassa
    r2 = client.post(f"/api/v1/orders/{token}/payment")
    assert r2.status_code == 201 and r2.json()["payment"]["yookassa_id"] == yk_id
    assert len(yookassa.payments) == 1

    # клиент вернулся, ещё не заплатив
    c = client.post(f"/api/v1/orders/{token}/payment/check").json()
    assert c["payment"]["status"] == "pending" and c["order_status"] == "new"
    assert len(tg_sent) == 1  # только «новый заказ»

    # клиент заплатил и вернулся
    yookassa.pay(yk_id)
    c = client.post(f"/api/v1/orders/{token}/payment/check").json()
    assert c["payment"]["status"] == "succeeded"
    assert c["payment"]["paid_at"] == "2026-10-20T01:02:03+00:00"
    assert c["order_status"] == "paid"
    g = client.get(f"/api/v1/orders/{token}").json()
    assert g["status"] == "paid" and g["payment"]["confirmation_url"] is None

    # владелец получил сообщение с кнопками следующих шагов
    assert len(tg_sent) == 2  # «новый заказ» + «оплачен»
    text, kb = tg_sent[1]
    assert "💰 Оплачен заказ ТУЦ-1" in text and "⚠️" not in text
    datas = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert "status:1:printing" in datas and "status:1:paid" not in datas

    # второй раз «Оплатить» нельзя
    assert client.post(f"/api/v1/orders/{token}/payment").status_code == 409

    # в БД — одна строка платежа с полным ответом ЮKassa
    with db.connect() as conn:
        from sqlalchemy import select

        rows = conn.execute(select(Payment.status, Payment.raw)).all()
    assert len(rows) == 1 and rows[0][0] == "succeeded" and rows[0][1]["id"] == yk_id


# --- вебхук ------------------------------------------------------------------------


def test_webhook_marks_paid_idempotently(client, pricing_file, fake_slicer, yookassa, tg_sent):
    order = _order(client)
    token = order["token"]
    yk_id = client.post(f"/api/v1/orders/{token}/payment").json()["payment"]["yookassa_id"]

    # подделка: тело говорит «успех», а ЮKassa на самом деле — «ожидает». Верим ЮKassa.
    forged = yookassa.webhook_body(yk_id)
    forged["event"] = "payment.succeeded"
    forged["object"] = {**forged["object"], "status": "succeeded", "paid": True}
    r = client.post("/api/v1/payments/yookassa/webhook", json=forged)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert client.get(f"/api/v1/orders/{token}").json()["status"] == "new"
    assert len(tg_sent) == 1  # только «новый заказ»

    # настоящая оплата
    yookassa.pay(yk_id)
    r = client.post("/api/v1/payments/yookassa/webhook", json=yookassa.webhook_body(yk_id))
    assert r.status_code == 200 and r.json() == {"ok": True, "status": "succeeded", "order_id": 1}
    assert client.get(f"/api/v1/orders/{token}").json()["status"] == "paid"
    assert len(tg_sent) == 2

    # тот же вебхук ещё раз — ничего не меняется, второго сообщения нет
    r = client.post("/api/v1/payments/yookassa/webhook", json=yookassa.webhook_body(yk_id))
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    assert len(tg_sent) == 2

    # владелец тем временем уже перевёл заказ в печать — вебхук не откатывает статус
    from app.db import get_db
    from app.orders import change_status

    s = next(get_db())
    change_status(s, 1, "printing")
    s.close()
    client.post("/api/v1/payments/yookassa/webhook", json=yookassa.webhook_body(yk_id))
    assert client.get(f"/api/v1/orders/{token}").json()["status"] == "printing"


def test_webhook_ignores_unknown_and_other_events(client, pricing_file, fake_slicer, yookassa):
    assert client.post(
        "/api/v1/payments/yookassa/webhook",
        json={"type": "notification", "event": "payment.succeeded", "object": {"id": "nope"}},
    ).json() == {"ok": True, "ignored": True}
    assert client.post(
        "/api/v1/payments/yookassa/webhook",
        json={"type": "notification", "event": "refund.succeeded", "object": {"id": "r1"}},
    ).json() == {"ok": True, "ignored": True}
    assert client.post(
        "/api/v1/payments/yookassa/webhook", content=b"not json",
        headers={"content-type": "application/json"},
    ).status_code == 422  # не JSON — FastAPI сам отвечает 422  # fmt: skip


def test_canceled_payment_allows_retry(client, pricing_file, fake_slicer, yookassa, tg_sent):
    order = _order(client)
    token = order["token"]
    first = client.post(f"/api/v1/orders/{token}/payment").json()["payment"]["yookassa_id"]
    yookassa.cancel(first)

    # вернулся с формы, платёж отменён — заказ остаётся «принят», сообщений владельцу нет
    c = client.post(f"/api/v1/orders/{token}/payment/check").json()
    assert c["payment"]["status"] == "canceled" and c["order_status"] == "new"
    assert len(tg_sent) == 1
    g = client.get(f"/api/v1/orders/{token}").json()
    assert g["payment"] == {
        "enabled": True,
        "status": "canceled",
        "confirmation_url": None,
        "paid_at": None,
    }

    # «Оплатить» снова — новый платёж в ЮKassa
    second = client.post(f"/api/v1/orders/{token}/payment").json()["payment"]["yookassa_id"]
    assert second != first and len(yookassa.payments) == 2


def test_cannot_pay_cancelled_order(client, pricing_file, fake_slicer, yookassa):
    from app.db import get_db
    from app.orders import change_status

    order = _order(client)
    s = next(get_db())
    change_status(s, order["id"], "cancelled")
    s.close()
    r = client.post(f"/api/v1/orders/{order['token']}/payment")
    assert r.status_code == 409
    assert client.post(f"/api/v1/orders/{order['token']}/payment/check").status_code == 404


def test_yookassa_down_or_wrong_keys(client, pricing_file, fake_slicer, yookassa, monkeypatch):
    order = _order(client)
    monkeypatch.setattr(settings, "yookassa_secret_key", "wrong")
    r = client.post(f"/api/v1/orders/{order['token']}/payment")
    assert r.status_code == 502 and "401" in r.json()["detail"]

    def boom(request):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(settings, "yookassa_secret_key", "test_key")
    monkeypatch.setattr(payments, "TRANSPORT", httpx.MockTransport(boom))
    r = client.post(f"/api/v1/orders/{order['token']}/payment")
    assert r.status_code == 502 and "недоступна" in r.json()["detail"]


def test_notify_owner_paid_warns_if_status_changed(tg_sent):
    order = {
        "id": 5, "number": "ТУЦ-5", "status": "cancelled", "total": 900, "token": "x" * 32,
        "customer_name": "Иван", "phone": "+79991234567", "material": "PLA", "qty": 1,
        "supports": False, "postprocess": "none", "delivery": "pickup",
    }  # fmt: skip
    assert telegram.notify_owner_paid(order) is True
    text, _ = tg_sent[-1]
    assert "💰 Оплачен заказ ТУЦ-5" in text and "⚠️" in text and "отменён" in text


def test_webhook_does_not_block_api_while_yookassa_is_slow(
    client, pricing_file, fake_slicer, yookassa
):
    """Пока ЮKassa долго отвечает на перечитывание платежа, остальные запросы (GET /health)
    должны обслуживаться. Раньше обработчик был `async def` и синхронно ждал ЮKassa —
    весь API замирал на время её ответа (один event loop).

    Поддельная ЮKassa «зависает»: в ответ на GET платежа ждёт события `release`. Вебхук
    уходит в отдельном потоке; дождавшись, что ЮKassa начала «думать», зовём /health.
    Если event loop свободен — ответ приходит сразу, до `release`. Если занят — /health
    висит, и его отпустит только страховочный таймер через 5 с (тогда тест падает).
    """
    import threading

    order = _order(client)
    yk_id = client.post(f"/api/v1/orders/{order['token']}/payment").json()["payment"]["yookassa_id"]
    started, release = threading.Event(), threading.Event()
    fast_handler = yookassa.handler

    def slow_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            started.set()
            release.wait(timeout=10)
        return fast_handler(request)

    payments.TRANSPORT = httpx.MockTransport(slow_handler)
    safety = threading.Timer(5, release.set)
    with TestClient(app) as shared_loop_client:  # внутри `with` все запросы — на одном event loop
        hook = threading.Thread(
            target=shared_loop_client.post,
            args=("/api/v1/payments/yookassa/webhook",),
            kwargs={"json": yookassa.webhook_body(yk_id)},
        )
        hook.start()
        assert started.wait(timeout=10), "вебхук так и не дошёл до ЮKassa"
        safety.start()
        health = shared_loop_client.get("/health")
        loop_was_free = not release.is_set()
        release.set()
        hook.join(timeout=10)
    safety.cancel()
    assert health.status_code == 200
    assert loop_was_free, "GET /health ждал ответа ЮKassa вебхуку — event loop был заблокирован"
