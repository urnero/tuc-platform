"""События воронки (B12): запись на каждом шаге, связь шагов, сводка, устойчивость к сбоям БД."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import REPO_ROOT, box_stl
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_payments import FakeYooKassa, _basic

from app import payments, telegram
from app.config import settings
from app.db import reset_engine
from app.events import funnel, track
from app.models import EVENT_NAMES, Event
from app.pricing import reload_pricing


@pytest.fixture
def pricing_file(monkeypatch):
    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    yield
    reload_pricing()


@pytest.fixture
def yookassa(monkeypatch):
    fake = FakeYooKassa()
    monkeypatch.setattr(settings, "yookassa_shop_id", "shop-1")
    monkeypatch.setattr(settings, "yookassa_secret_key", "test_key")
    monkeypatch.setattr(settings, "site_url", "https://tuc.example")
    monkeypatch.setattr(telegram, "send_message", lambda *a, **k: True)
    monkeypatch.setattr(payments, "TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


def _events(db) -> list[Event]:
    with Session(db) as s:
        return list(s.scalars(select(Event).order_by(Event.id)))


def _upload(client) -> str:
    r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _quote(client, upload_id: str, qty: int = 1) -> dict:
    client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    r = client.post(
        f"/api/v1/uploads/{upload_id}/quote",
        json={"material": "PLA", "qty": qty, "delivery": "pickup"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _order(client, quote_id: str) -> dict:
    r = client.post(
        "/api/v1/orders",
        json={"quote_id": quote_id, "name": "Иван", "phone": "9991234567", "consent": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- полный путь клиента --------------------------------------------------------


def test_full_funnel_is_recorded(client, pricing_file, fake_slicer, yookassa, db):
    upload_id = _upload(client)
    quote = _quote(client, upload_id, qty=2)
    order = _order(client, quote["id"])
    token = order["token"]

    p = client.post(f"/api/v1/orders/{token}/payment").json()
    yookassa.pay(p["payment"]["yookassa_id"])
    assert client.post(f"/api/v1/orders/{token}/payment/check").json()["order_status"] == "paid"

    rows = _events(db)
    assert [e.name for e in rows] == list(EVENT_NAMES)

    upload, quote_ev, order_ev, started, paid = rows
    # все шаги склеиваются по upload_id, а шаги после заказа — ещё и по order_id
    assert {e.upload_id for e in rows} == {upload_id}
    assert quote_ev.quote_id == quote["id"] == order_ev.quote_id
    assert order_ev.order_id == started.order_id == paid.order_id == order["id"]
    assert upload.order_id is None and quote_ev.order_id is None

    # детали шагов
    assert upload.props["ext"] == "stl" and upload.props["size_bytes"] > 0
    assert upload.props["watertight"] is True
    assert quote_ev.props == {
        "material": "PLA",
        "supports": False,
        "qty": 2,
        "postprocess": "none",
        "delivery": "pickup",
        "total": quote["total"],
    }
    assert order_ev.props == {"total": order["total"], "delivery": "pickup", "qty": 2}
    assert started.props["amount"] == order["total"] == paid.props["amount"]
    assert paid.props["yookassa_id"] == p["payment"]["yookassa_id"]
    assert all(e.created_at is not None for e in rows)
    assert paid.to_dict()["created_at"].endswith("+00:00")


def test_paid_is_written_once_even_if_webhook_repeats(
    client, pricing_file, fake_slicer, yookassa, db
):
    upload_id = _upload(client)
    order = _order(client, _quote(client, upload_id)["id"])
    token = order["token"]
    p = client.post(f"/api/v1/orders/{token}/payment").json()
    yk_id = p["payment"]["yookassa_id"]
    yookassa.pay(yk_id)

    event = {
        "type": "notification",
        "event": "payment.succeeded",
        "object": yookassa.payments[yk_id],
    }
    for _ in range(3):
        assert client.post("/api/v1/payments/yookassa/webhook", json=event).status_code == 200
    client.post(f"/api/v1/orders/{token}/payment/check")

    names = [e.name for e in _events(db)]
    assert names.count("paid") == 1 and names.count("payment_started") == 1


def test_repeated_pay_click_does_not_duplicate_payment_started(
    client, pricing_file, fake_slicer, yookassa, db
):
    """Пока форма ЮKassa открыта, повторное «Оплатить» возвращает тот же платёж — без события."""
    order = _order(client, _quote(client, _upload(client))["id"])
    token = order["token"]
    client.post(f"/api/v1/orders/{token}/payment")
    client.post(f"/api/v1/orders/{token}/payment")
    assert [e.name for e in _events(db)].count("payment_started") == 1


def test_failed_steps_leave_no_events(client, pricing_file, fake_slicer, db):
    """Отклонённая загрузка, расчёт без слайсинга, заказ без согласия — не шаги воронки."""
    assert client.post("/api/v1/uploads", files={"file": ("x.obj", b"xx", "x")}).status_code == 415
    upload_id = _upload(client)
    r = client.post(f"/api/v1/uploads/{upload_id}/quote", json={"material": "PLA"})
    assert r.status_code == 409
    quote = _quote(client, upload_id)
    r = client.post(
        "/api/v1/orders", json={"quote_id": quote["id"], "name": "И", "phone": "9991234567"}
    )
    assert r.status_code == 422
    assert [e.name for e in _events(db)] == ["upload", "quote"]


# --- track() сам по себе ----------------------------------------------------------


def test_track_unknown_name():
    with pytest.raises(ValueError, match="Неизвестное событие"):
        track("click")


def test_track_survives_broken_db(client, data_dir, monkeypatch, caplog):
    """БД недоступна → загрузка всё равно проходит, в логе предупреждение, события нет."""
    monkeypatch.setattr(settings, "database_url", "sqlite:////nonexistent-dir/x/y/z.db")
    reset_engine()
    with caplog.at_level(logging.WARNING, logger="app.events"):
        assert track("upload", upload_id="a" * 32) is None
        r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    assert r.status_code == 201
    assert "не записано" in caplog.text
    reset_engine()


# --- сводка -------------------------------------------------------------------------


def test_funnel_counts_unique_uploads_and_orders(db):
    with Session(db) as s:
        old = datetime.now(UTC) - timedelta(days=40)
        u1, u2, u3 = "a" * 32, "b" * 32, "c" * 32
        # u1: три расчёта по одной модели, заказ, оплата
        track("upload", upload_id=u1, db=s)
        for i in range(3):
            track("quote", upload_id=u1, quote_id=f"{u1}-00000{i}", db=s)
        track("order", upload_id=u1, order_id=1, db=s)
        track("payment_started", upload_id=u1, order_id=1, db=s)
        track("payment_started", upload_id=u1, order_id=1, db=s)  # передумал, вернулся
        track("paid", upload_id=u1, order_id=1, db=s)
        # u2: только загрузка и расчёт
        track("upload", upload_id=u2, db=s)
        track("quote", upload_id=u2, quote_id=f"{u2}-000000", db=s)
        # u3: давно — в 30 дней не попадает
        e = track("upload", upload_id=u3, db=s)
        e.created_at = old
        s.commit()

        assert funnel(s) == {
            "upload": 2,
            "quote": 2,
            "order": 1,
            "payment_started": 1,
            "paid": 1,
        }
        assert funnel(s, days=60)["upload"] == 3
        assert funnel(s, days=0) == {name: 0 for name in EVENT_NAMES}


def test_admin_shows_funnel(client, pricing_file, fake_slicer, db, monkeypatch):
    monkeypatch.setattr(settings, "admin_user", "girg")
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    _order(client, _quote(client, _upload(client))["id"])
    _upload(client)  # вторая модель без расчёта

    r = client.get(
        "/admin/orders", headers={"Authorization": "Basic " + _basic("girg", "secret-pass")}
    )
    assert r.status_code == 200
    html = r.text
    assert "Воронка за 30 дней" in html
    assert "загрузок <b>2</b>" in html
    assert "расчётов <b>1</b>" in html
    assert "заказов <b>1</b>" in html
    assert "оплат <b>0</b>" in html
