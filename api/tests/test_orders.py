"""Заказы (B06): телефон, создание заказа, страница статуса, миграции Alembic."""

import pytest
from alembic.config import Config
from conftest import REPO_ROOT, box_stl
from sqlalchemy import create_engine, inspect, select

from alembic import command
from app.config import settings
from app.db import Base
from app.models import ORDER_STATUSES, Order
from app.orders import PhoneError, normalize_phone
from app.pricing import reload_pricing

PRICING_YAML = REPO_ROOT / "config" / "pricing.yaml"


@pytest.fixture
def pricing_file(monkeypatch):
    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", PRICING_YAML)
    yield
    reload_pricing()


# --- телефон -----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+7 999 123-45-67", "+79991234567"),
        ("8 (999) 123 45 67", "+79991234567"),
        ("9991234567", "+79991234567"),
        ("+79991234567", "+79991234567"),
        ("+375 29 123 45 67", "+375291234567"),  # иностранный с «+» — оставляем
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "123", "999123", "12345678901234567", "abc"])
def test_normalize_phone_bad(raw):
    with pytest.raises(PhoneError):
        normalize_phone(raw)


# --- API ---------------------------------------------------------------------


def _quote(client, delivery="pickup", qty=1) -> dict:
    """Загрузка → расчёт печати (поддельный слайсер) → расчёт цены."""
    r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    assert r.status_code == 201
    upload_id = r.json()["id"]
    s = client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    assert s.status_code == 202 and s.json()["status"] == "done"
    q = client.post(
        f"/api/v1/uploads/{upload_id}/quote",
        json={"material": "PLA", "qty": qty, "delivery": delivery},
    )
    assert q.status_code == 201
    return q.json()


GOOD = {"name": "  Иван ", "phone": "8 999 123-45-67", "consent": True}


def test_create_order_pickup(client, pricing_file, fake_slicer, db):
    quote = _quote(client, qty=2)
    r = client.post("/api/v1/orders", json={**GOOD, "quote_id": quote["id"], "comment": " срочно "})
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["id"] == 1 and o["number"] == "ТУЦ-1"
    assert len(o["token"]) == 32
    assert o["status"] == "new"
    assert o["customer_name"] == "Иван"
    assert o["phone"] == "+79991234567"
    assert o["email"] is None
    assert o["delivery"] == "pickup" and o["address"] is None
    assert o["comment"] == "срочно"
    assert o["upload_id"] == quote["upload_id"]
    assert o["quote_id"] == quote["id"]
    assert o["original_name"] == "box.stl"
    assert o["material"] == "PLA" and o["qty"] == 2 and o["supports"] is False
    assert o["total"] == quote["total"]
    assert o["quote"]["id"] == quote["id"]  # снимок расчёта целиком
    assert o["created_at"].endswith("+00:00")

    # заказ лежит в БД
    with db.connect() as conn:
        row = conn.execute(select(Order.id, Order.phone, Order.total)).one()
    assert row == (1, "+79991234567", quote["total"])

    # второй заказ получает следующий номер
    r2 = client.post("/api/v1/orders", json={**GOOD, "quote_id": quote["id"]})
    assert r2.status_code == 201 and r2.json()["id"] == 2


def test_create_order_courier_needs_address(client, pricing_file, fake_slicer):
    quote = _quote(client, delivery="courier_moscow")
    r = client.post("/api/v1/orders", json={**GOOD, "quote_id": quote["id"]})
    assert r.status_code == 422
    assert "адрес" in r.json()["detail"]

    r = client.post(
        "/api/v1/orders",
        json={**GOOD, "quote_id": quote["id"], "address": "Москва, Тверская 1", "email": "a@b.ru"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["delivery"] == "courier_moscow"
    assert r.json()["address"] == "Москва, Тверская 1"
    assert r.json()["email"] == "a@b.ru"


@pytest.mark.parametrize(
    "patch, text",
    [
        ({"consent": False}, "согласие"),
        ({"name": "   "}, "обращаться"),
        ({"phone": "123"}, "телефон"),
        ({"email": "not-an-email"}, "e-mail"),
    ],
)
def test_create_order_validation(client, pricing_file, fake_slicer, patch, text):
    quote = _quote(client)
    r = client.post("/api/v1/orders", json={**GOOD, "quote_id": quote["id"], **patch})
    assert r.status_code == 422, r.text
    assert text in str(r.json()["detail"])


def test_create_order_quote_not_found(client, pricing_file):
    r = client.post("/api/v1/orders", json={**GOOD, "quote_id": "0" * 32 + "-abcdef"})
    assert r.status_code == 404
    r = client.post("/api/v1/orders", json={**GOOD, "quote_id": "../etc/passwd"})
    assert r.status_code == 404


def test_get_order_by_token(client, pricing_file, fake_slicer):
    quote = _quote(client)
    created = client.post("/api/v1/orders", json={**GOOD, "quote_id": quote["id"]}).json()
    r = client.get(f"/api/v1/orders/{created['token']}")
    assert r.status_code == 200
    assert r.json() == created

    assert client.get("/api/v1/orders/" + "f" * 32).status_code == 404
    assert client.get("/api/v1/orders/1").status_code == 404  # по номеру — нельзя


def test_statuses_start_with_new():
    assert ORDER_STATUSES[0] == "new"
    assert "paid" in ORDER_STATUSES and "cancelled" in ORDER_STATUSES


# --- миграции ------------------------------------------------------------------


def _columns(insp, table) -> dict:
    return {c["name"]: (type(c["type"]).__name__, c["nullable"]) for c in insp.get_columns(table)}


def _indexes(insp, table) -> set:
    return {(i["name"], tuple(i["column_names"]), i["unique"]) for i in insp.get_indexes(table)}


def test_alembic_matches_models(tmp_path, monkeypatch):
    """`alembic upgrade head` создаёт те же таблицы и колонки, что описаны в app/models.py."""
    import app.models  # noqa: F401

    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(REPO_ROOT / "api" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "api" / "alembic"))
    command.upgrade(cfg, "head")

    migrated = inspect(create_engine(url))
    model_engine = create_engine(f"sqlite:///{tmp_path / 'models.db'}")
    Base.metadata.create_all(model_engine)
    expected = inspect(model_engine)

    assert set(migrated.get_table_names()) - {"alembic_version"} == set(expected.get_table_names())
    for table in expected.get_table_names():
        assert _columns(migrated, table) == _columns(expected, table), table
        assert _indexes(migrated, table) == _indexes(expected, table), table

    # откат тоже работает
    command.downgrade(cfg, "base")
    assert "orders" not in inspect(create_engine(url)).get_table_names()
