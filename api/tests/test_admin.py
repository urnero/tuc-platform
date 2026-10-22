"""Админка (B09): вход по basic auth, список и фильтры, карточка, статус, файлы, CSV."""

import base64
import csv
from datetime import UTC, datetime

import pytest
from conftest import REPO_ROOT, box_stl

from app.config import settings
from app.db import session_factory
from app.models import Order, Payment
from app.pricing import reload_pricing

AUTH = {"Authorization": "Basic " + base64.b64encode(b"girg:secret-pass").decode()}


@pytest.fixture
def pricing_file(monkeypatch):
    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    yield
    reload_pricing()


@pytest.fixture
def admin_on(monkeypatch):
    monkeypatch.setattr(settings, "admin_user", "girg")
    monkeypatch.setattr(settings, "admin_password", "secret-pass")


def _order(client, name="Иван", phone="8 999 123-45-67", qty=1, delivery="pickup") -> dict:
    """Загрузка → расчёт печати (поддельный слайсер) → цена → заказ."""
    r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    upload_id = r.json()["id"]
    client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    q = client.post(
        f"/api/v1/uploads/{upload_id}/quote",
        json={"material": "PLA", "qty": qty, "delivery": delivery},
    ).json()
    body = {"quote_id": q["id"], "name": name, "phone": phone, "consent": True}
    if delivery != "pickup":
        body["address"] = "Москва, Тверская 1"
    r = client.post("/api/v1/orders", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- вход --------------------------------------------------------------------


def test_admin_disabled_without_password(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "")
    r = client.get("/admin/orders")
    assert r.status_code == 503
    assert "ADMIN_PASSWORD" in r.json()["detail"]


def test_admin_requires_basic_auth(client, admin_on):
    r = client.get("/admin/orders")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")

    bad = {"Authorization": "Basic " + base64.b64encode(b"girg:wrong").decode()}
    assert client.get("/admin/orders", headers=bad).status_code == 401
    assert client.get("/admin/orders/1/file", headers=bad).status_code == 401

    r = client.get("/admin", headers=AUTH, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/orders"


# --- список и фильтры ---------------------------------------------------------


def test_orders_list_filters_and_search(client, admin_on, pricing_file, fake_slicer, db):
    r = client.get("/admin/orders", headers=AUTH)
    assert r.status_code == 200 and "Заказов нет" in r.text

    _order(client, name="Иван", phone="8 999 123-45-67")
    _order(client, name="Мария", phone="+7 926 000-11-22", qty=3, delivery="courier_moscow")
    with session_factory()() as s:
        s.get(Order, 2).status = "done"
        s.commit()

    r = client.get("/admin/orders", headers=AUTH)
    assert r.status_code == 200
    assert "ТУЦ-1" in r.text and "ТУЦ-2" in r.text
    assert "+7 999 123-45-67" in r.text and "курьер по Москве" in r.text
    assert "В работе (1)" in r.text  # done — не в работе

    r = client.get("/admin/orders?status=active", headers=AUTH)
    assert "ТУЦ-1" in r.text and "ТУЦ-2" not in r.text
    r = client.get("/admin/orders?status=done", headers=AUTH)
    assert "ТУЦ-1" not in r.text and "ТУЦ-2" in r.text
    r = client.get("/admin/orders?status=nonsense", headers=AUTH)  # неизвестный фильтр = все
    assert "ТУЦ-1" in r.text and "ТУЦ-2" in r.text

    # поиск: по номеру, по хвосту телефона, по имени (без учёта регистра)
    r = client.get("/admin/orders?q=ТУЦ-2", headers=AUTH)
    assert "ТУЦ-2" in r.text and "ТУЦ-1" not in r.text
    r = client.get("/admin/orders?q=4567", headers=AUTH)
    assert "ТУЦ-1" in r.text and "ТУЦ-2" not in r.text
    r = client.get("/admin/orders?q=мария", headers=AUTH)
    assert "ТУЦ-2" in r.text and "ТУЦ-1" not in r.text
    r = client.get("/admin/orders?q=никого", headers=AUTH)
    assert "Заказов нет" in r.text


def test_orders_list_pagination(client, admin_on, pricing_file, fake_slicer, db, monkeypatch):
    monkeypatch.setattr("app.admin.PAGE_SIZE", 2)
    for i in range(3):
        _order(client, name=f"Клиент {i}")
    r = client.get("/admin/orders", headers=AUTH)
    assert "ТУЦ-3" in r.text and "ТУЦ-2" in r.text and "ТУЦ-1" not in r.text
    assert "Страница 1 из 2" in r.text and "/admin/orders?page=2" in r.text
    r = client.get("/admin/orders?page=2", headers=AUTH)
    assert "ТУЦ-1" in r.text and "ТУЦ-3" not in r.text
    r = client.get("/admin/orders?page=99", headers=AUTH)  # за концом — последняя страница
    assert "Страница 2 из 2" in r.text


def test_orders_csv(client, admin_on, pricing_file, fake_slicer, db):
    _order(client, name="Иван; Петров", qty=2)
    with session_factory()() as s:
        s.add(
            Payment(
                order_id=1,
                yookassa_id="pay-1",
                idempotence_key="k1",
                status="succeeded",
                amount=900,
                paid_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
            )
        )
        s.commit()

    r = client.get("/admin/orders.csv", headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")  # BOM для Excel
    header, row = text.splitlines()
    assert header.startswith("id;number;created_msk;status;")
    cols = dict(zip(header.split(";"), next(csv.reader([row], delimiter=";")), strict=True))
    assert cols["number"] == "ТУЦ-1"
    assert cols["customer_name"] == "Иван; Петров"  # точка с запятой внутри — в кавычках
    assert cols["qty"] == "2" and cols["status_label"] == "принят"
    assert cols["paid_msk"] == "20.10.2026 12:00"

    r = client.get("/admin/orders.csv?status=done", headers=AUTH)
    assert len(r.content.decode("utf-8-sig").splitlines()) == 1  # только заголовок


def test_orders_csv_escapes_formulas(client, admin_on, pricing_file, fake_slicer, db):
    """QA 2026-10-22: имя клиента «=HYPERLINK(...)» в CSV не должно стать формулой Excel."""
    _order(client, name='=HYPERLINK("http://evil.example";"жми")')
    text = client.get("/admin/orders.csv", headers=AUTH).content.decode("utf-8-sig")
    header, row = text.splitlines()
    cols = dict(zip(header.split(";"), next(csv.reader([row], delimiter=";")), strict=True))
    assert cols["customer_name"].startswith("'=HYPERLINK")
    assert cols["id"] == "1"  # числа и обычный текст не трогаем
    assert cols["phone"] == "+79991234567"  # телефон с «+» — не формула

    from app.admin import csv_safe

    assert csv_safe("-2+3+cmd|' /C calc'!A0") == "'-2+3+cmd|' /C calc'!A0"
    assert csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert csv_safe("-5") == "-5" and csv_safe("") == "" and csv_safe(7) == 7


# --- карточка, статус, файлы -------------------------------------------------------


def test_order_page_and_status_change(client, admin_on, pricing_file, fake_slicer, db):
    o = _order(client, name="Иван", qty=2)
    r = client.get("/admin/orders/1", headers=AUTH)
    assert r.status_code == 200
    assert "Заказ ТУЦ-1" in r.text and "Иван" in r.text
    assert "Итого" in r.text and "Онлайн-оплату не начинали" in r.text
    assert f"/order/{o['token']}" in r.text
    assert "/admin/orders/1/file" in r.text and "/admin/orders/1/gcode" in r.text

    assert client.get("/admin/orders/999", headers=AUTH).status_code == 404

    # кнопка статуса: POST → 303 обратно на карточку с сообщением
    r = client.post(
        "/admin/orders/1/status", data={"status": "printing"}, headers=AUTH, follow_redirects=False
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/admin/orders/1?ok=")
    with session_factory()() as s:
        assert s.get(Order, 1).status == "printing"
    r = client.get(r.headers["location"], headers=AUTH)
    assert "статус «печатается»" in r.text

    # тот же статус ещё раз — ошибка, но не 500
    r = client.post(
        "/admin/orders/1/status", data={"status": "printing"}, headers=AUTH, follow_redirects=False
    )
    assert "err=" in r.headers["location"]
    r = client.post(
        "/admin/orders/1/status", data={"status": "nonsense"}, headers=AUTH, follow_redirects=False
    )
    assert "err=" in r.headers["location"]

    # форма с чужого сайта — браузер пришлёт Sec-Fetch-Site: cross-site → 403
    r = client.post(
        "/admin/orders/1/status",
        data={"status": "done"},
        headers={**AUTH, "Sec-Fetch-Site": "cross-site"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    with session_factory()() as s:
        assert s.get(Order, 1).status == "printing"


def test_download_model_and_gcode(client, admin_on, pricing_file, fake_slicer, db):
    _order(client)
    r = client.get("/admin/orders/1/file", headers=AUTH)
    assert r.status_code == 200
    assert r.content == box_stl()
    assert "box.stl" in r.headers["content-disposition"]

    r = client.get("/admin/orders/1/gcode", headers=AUTH)
    assert r.status_code == 200
    assert r.text.startswith("; generated by PrusaSlicer")
    assert "TUC-1_PLA.gcode" in r.headers["content-disposition"]

    # файлы удалили с диска — честные 404, карточка открывается
    for p in (settings.data_dir / "uploads").rglob("*"):
        if p.is_file() and p.suffix in (".stl", ".gcode"):
            p.unlink()
    assert client.get("/admin/orders/1/file", headers=AUTH).status_code == 404
    assert client.get("/admin/orders/1/gcode", headers=AUTH).status_code == 404
    r = client.get("/admin/orders/1", headers=AUTH)
    assert r.status_code == 200 and "файла нет на диске" in r.text
