"""B2B (B33): заказ от организации — ИНН/КПП, оплата по счёту, карточка в Telegram,
выгрузка, админка."""

import base64

import httpx
import pytest
from conftest import REPO_ROOT, box_stl
from sqlalchemy import select

from app import payments, telegram
from app.b2b import Company, inn_kind, is_valid_kpp
from app.config import settings
from app.db import session_factory
from app.export import COLUMNS, order_row
from app.models import Event, Order
from app.pricing import reload_pricing

ORG = {
    "name": " ООО «Ромашка» ",
    "inn": "7707083893",
    "kpp": "770101001",
    "address": "Москва, Тверская, 1",
}
IP = {"name": "ИП Иванов И. И.", "inn": "500100732259"}


@pytest.fixture
def pricing_file(monkeypatch):
    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    yield
    reload_pricing()


def _quote(client) -> dict:
    r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    upload_id = r.json()["id"]
    s = client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    assert s.status_code == 202 and s.json()["status"] == "done"
    q = client.post(
        f"/api/v1/uploads/{upload_id}/quote",
        json={"material": "PLA", "qty": 5, "delivery": "pickup"},
    )
    assert q.status_code == 201
    return q.json()


def _order(client, company: dict | None = ORG, email: str | None = "buh@romashka.ru", **extra):
    quote = _quote(client)
    body = {"quote_id": quote["id"], "name": "Иван", "phone": "9991234567", "consent": True}
    if email:
        body["email"] = email
    if company is not None:
        body["company"] = company
    body.update(extra)
    return client.post("/api/v1/orders", json=body)


# --- ИНН и КПП ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "inn, kind",
    [
        ("7707083893", "org"),  # Сбербанк — настоящий ИНН организации
        ("7736050003", "org"),  # Газпром
        ("500100732259", "ip"),  # пример ИНН физлица из справочников
        ("77 070 83893", "org"),  # пробелы терпим
        ("7707083894", None),  # контрольная цифра не сходится
        ("500100732258", None),
        ("123", None),
        ("", None),
        ("77070838aa", None),
        ("77070838931", None),  # 11 цифр — такого не бывает
    ],
)
def test_inn_kind(inn, kind):
    assert inn_kind(inn) == kind


@pytest.mark.parametrize(
    "kpp, ok", [("770101001", True), ("7701AB001", True), ("77010100", False), ("", False)]
)
def test_is_valid_kpp(kpp, ok):
    assert is_valid_kpp(kpp) is ok


def test_company_strips_and_drops_kpp_for_ip():
    c = Company(**ORG)
    assert c.name == "ООО «Ромашка»"
    assert c.to_columns()["company_kpp"] == "770101001"
    # У ИП КПП не бывает — даже присланный не сохраняем.
    assert Company(**IP, kpp="770101001").to_columns()["company_kpp"] is None


# --- заказ -----------------------------------------------------------------------


def test_create_order_from_company(client, pricing_file, fake_slicer, db):
    r = _order(client)
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["payment_method"] == "invoice"
    assert o["company"] == {
        "name": "ООО «Ромашка»",
        "inn": "7707083893",
        "kpp": "770101001",
        "address": "Москва, Тверская, 1",
    }
    # По счёту онлайн не платят — кнопки «Оплатить» на сайте не будет даже с ключами ЮKassa.
    assert o["payment"]["enabled"] is False

    with session_factory()() as s:
        row = s.scalar(select(Order))
        assert row.company_name == "ООО «Ромашка»" and row.company_inn == "7707083893"
        ev = s.scalar(select(Event).where(Event.name == "order"))
        assert ev.props["payment_method"] == "invoice" and ev.props["b2b"] is True


def test_create_order_private_person_unchanged(client, pricing_file, fake_slicer):
    o = _order(client, company=None, email=None).json()
    assert o["payment_method"] == "online" and o["company"] is None


def test_company_order_needs_email(client, pricing_file, fake_slicer):
    r = _order(client, email=None)
    assert r.status_code == 422
    assert "e-mail" in r.json()["detail"]


@pytest.mark.parametrize(
    "company, text",
    [
        ({**ORG, "inn": "7707083894"}, "ИНН"),
        ({**ORG, "kpp": "12"}, "КПП"),
        ({**ORG, "name": "   "}, "наименование"),
        ({"inn": "7707083893"}, "name"),
    ],
)
def test_company_validation(client, pricing_file, fake_slicer, company, text):
    r = _order(client, company=company)
    assert r.status_code == 422
    assert text in r.text


def test_invoice_order_cannot_pay_online(client, pricing_file, fake_slicer, monkeypatch):
    monkeypatch.setattr(settings, "yookassa_shop_id", "shop-1")
    monkeypatch.setattr(settings, "yookassa_secret_key", "test_key")

    def no_network(request):  # до ЮKassa дойти не должны
        raise AssertionError("ЮKassa не должна вызываться для заказа по счёту")

    monkeypatch.setattr(payments, "TRANSPORT", httpx.MockTransport(no_network))
    o = _order(client).json()
    assert client.get(f"/api/v1/orders/{o['token']}").json()["payment"]["enabled"] is False
    r = client.post(f"/api/v1/orders/{o['token']}/payment")
    assert r.status_code == 409
    assert "по счёту" in r.json()["detail"]


# --- Telegram, выгрузка, админка ----------------------------------------------


def test_order_card_shows_company(client, pricing_file, fake_slicer):
    o = _order(client).json()
    text = telegram.order_card(o)
    assert "Юрлицо: ООО «Ромашка», ИНН 7707083893, КПП 770101001 · оплата по счёту" in text
    o2 = _order(client, company=None, email=None).json()
    assert "Юрлицо" not in telegram.order_card(o2)


def test_export_columns_end_with_company(client, pricing_file, fake_slicer):
    assert COLUMNS[-3:] == ["company_name", "company_inn", "payment_method"]
    _order(client)
    with session_factory()() as s:
        row = order_row(s.scalar(select(Order)), None)
    as_dict = dict(zip(COLUMNS, row, strict=True))
    assert as_dict["company_name"] == "ООО «Ромашка»"
    assert as_dict["company_inn"] == "7707083893"
    assert as_dict["payment_method"] == "invoice"


def test_admin_shows_company_and_finds_by_inn(client, pricing_file, fake_slicer, monkeypatch):
    monkeypatch.setattr(settings, "admin_user", "girg")
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    auth = {"Authorization": "Basic " + base64.b64encode(b"girg:secret-pass").decode()}
    o = _order(client).json()
    _order(client, company=None, email=None)

    page = client.get(f"/admin/orders/{o['id']}", headers=auth)
    assert page.status_code == 200
    assert "ООО «Ромашка»" in page.text and "ИНН 7707083893" in page.text
    assert f"/order/{o['token']}/invoice" in page.text

    found = client.get("/admin/orders", params={"q": "7707083893"}, headers=auth)
    assert found.text.count("BP-") >= 1 and "BP-2" not in found.text.split("<tbody>")[1]
    found = client.get("/admin/orders", params={"q": "ромашка"}, headers=auth)
    assert "по счёту" in found.text
