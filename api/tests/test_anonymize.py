"""Обезличивание заказов старше 5 лет по политике ПДн (B35, app/anonymize.py)."""

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import anonymize, worker
from app.config import settings
from app.models import Lead, Order, Payment

NOW = datetime(2031, 11, 1, 1, 50, tzinfo=UTC)
FIVE_YEARS = 5 * 365 + 1


def _order(db, status: str, closed_days_ago: float, **extra) -> Order:
    when = NOW - timedelta(days=closed_days_ago)
    fields = dict(
        token=secrets.token_hex(16),
        status=status,
        created_at=when - timedelta(days=3),
        updated_at=when,
        customer_name="Иван Петров",
        phone="+79991234567",
        email="ivan@example.com",
        delivery="courier_moscow",
        address="Москва, ул. Пушкина, 1",
        comment="позвонить перед доставкой",
        company_name="ООО Ромашка",
        company_inn="7707083893",
        company_kpp="770701001",
        company_address="Москва, Тверская, 2",
        telegram_chat_id="777",
        upload_id=secrets.token_hex(16),
        quote_id="q1",
        original_name="box.stl",
        material="PLA",
        qty=3,
        total=900,
        quote={"total": 900, "material": "PLA"},
    )
    fields.update(extra)
    order = Order(**fields)
    db.add(order)
    db.commit()
    return order


def _payment(db, order: Order, raw: dict | None) -> Payment:
    p = Payment(
        order_id=order.id,
        yookassa_id=secrets.token_hex(8),
        idempotence_key=secrets.token_hex(8),
        status="succeeded",
        amount=order.total,
        raw=raw if raw is not None else {},
    )
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def session(db):
    with Session(db) as s:
        yield s


def _fresh(session, order_id: int) -> Order:
    session.expire_all()
    return session.get(Order, order_id)


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_old_closed_orders_are_anonymized(session, status):
    old = _order(session, status, closed_days_ago=FIVE_YEARS + 1)
    on_edge = _order(session, status, closed_days_ago=FIVE_YEARS)
    recent = _order(session, status, closed_days_ago=FIVE_YEARS - 1)
    pay = _payment(session, old, raw={"payment_method": {"card": {"last4": "4242"}}})
    old_updated_at = old.updated_at

    report = anonymize.anonymize_orders(session, now=NOW)

    assert report.orders == [old.id, on_edge.id]
    assert report.payments == 1
    o = _fresh(session, old.id)
    assert o.customer_name == "" and o.phone == ""
    assert o.email is None and o.address is None and o.comment is None
    assert o.company_name is None and o.company_inn is None and o.company_kpp is None
    assert o.company_address is None and o.telegram_chat_id is None
    assert o.anonymized_at is not None
    # остаётся всё, что нужно учёту и аналитике
    assert o.status == status and o.total == 900 and o.material == "PLA" and o.qty == 3
    assert o.quote == {"total": 900, "material": "PLA"}
    assert o.original_name == "box.stl" and o.token
    # дата закрытия заказа не сдвинулась
    assert o.updated_at.replace(tzinfo=UTC) == old_updated_at.replace(tzinfo=UTC)
    # оплата: сырой ответ ЮKassa стёрт, суммы и id на месте
    p = session.get(Payment, pay.id)
    assert p.raw == {} and p.amount == 900 and p.status == "succeeded"

    r = _fresh(session, recent.id)
    assert r.customer_name == "Иван Петров" and r.anonymized_at is None


def test_active_orders_are_never_anonymized(session):
    # Заказ в работе — пусть хоть десять лет — данные нужны, чтобы его выполнить.
    for status in ("new", "paid", "printing", "ready"):
        o = _order(session, status, closed_days_ago=4000)
        anonymize.anonymize_orders(session, now=NOW)
        o = _fresh(session, o.id)
        assert o.customer_name == "Иван Петров" and o.anonymized_at is None, status


def test_already_anonymized_is_skipped(session):
    o = _order(session, "done", closed_days_ago=4000)
    assert anonymize.anonymize_orders(session, now=NOW).orders == [o.id]
    first = _fresh(session, o.id).anonymized_at
    # второй прогон не находит его снова и не переписывает дату
    assert anonymize.anonymize_orders(session, now=NOW + timedelta(days=1)).orders == []
    assert _fresh(session, o.id).anonymized_at == first


def test_dry_run_changes_nothing(session):
    o = _order(session, "done", closed_days_ago=4000)
    _payment(session, o, raw={"id": "x"})
    report = anonymize.anonymize_orders(session, now=NOW, dry_run=True)
    assert report.orders == [o.id] and report.payments == 1 and report.dry_run
    o = _fresh(session, o.id)
    assert o.customer_name == "Иван Петров" and o.anonymized_at is None
    assert session.execute(select(Payment.raw)).scalar_one() == {"id": "x"}


def test_zero_setting_disables(session, monkeypatch):
    monkeypatch.setattr(settings, "anonymize_orders_days", 0)
    o = _order(session, "done", closed_days_ago=4000)
    assert anonymize.anonymize_orders(session, now=NOW).orders == []
    assert _fresh(session, o.id).customer_name == "Иван Петров"


def test_api_shows_anonymized_order(client, db):
    """Страница заказа по токену открывается и после обезличивания: статус и сумма есть,
    контактов нет, в ответе дата `anonymized_at`."""
    with Session(db) as s:
        o = _order(s, "done", closed_days_ago=4000)
        token = o.token
        anonymize.anonymize_orders(s, now=NOW)
    r = client.get(f"/api/v1/orders/{token}")
    assert r.status_code == 200
    body = r.json()
    assert body["customer_name"] == "" and body["phone"] == "" and body["email"] is None
    assert body["company"] is None
    assert body["total"] == 900 and body["status"] == "done"
    assert body["anonymized_at"].startswith("2031-11-01")
    assert body["notifications"] == {"email": None, "telegram_linked": False, "telegram_link": None}


def test_cli_and_cron(db, capsys):
    with Session(db) as s:
        o = _order(s, "done", closed_days_ago=4000)
        _payment(s, o, raw={"id": "x"})
        _order(s, "done", closed_days_ago=10)
        old_id = o.id

    assert anonymize.main(["--dry-run"]) == 0
    assert "обезличилось бы: 1" in capsys.readouterr().out
    with Session(db) as s:
        assert _fresh(s, old_id).customer_name == "Иван Петров"

    assert anonymize.main([]) == 0
    out = capsys.readouterr().out
    assert "обезличено: 1" in out and "ЮKassa: 1" in out
    with Session(db) as s:
        assert _fresh(s, old_id).customer_name == ""

    assert worker.anonymize_orders in worker.WorkerSettings.functions
    assert "cron:anonymize_orders" in [c.name for c in worker.WorkerSettings.cron_jobs]


def test_admin_card_after_anonymize(client, db, monkeypatch):
    """Карточка в админке открывается: вместо контактов прочерки и пометка о стирании."""
    import base64

    monkeypatch.setattr(settings, "admin_user", "girg")
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    auth = {"Authorization": "Basic " + base64.b64encode(b"girg:secret-pass").decode()}
    with Session(db) as s:
        o = _order(s, "done", closed_days_ago=4000)
        order_id = o.id
        anonymize.anonymize_orders(s, now=NOW)
    r = client.get(f"/admin/orders/{order_id}", headers=auth)
    assert r.status_code == 200
    assert "Данные клиента стёрты 01.11.2031" in r.text
    assert "Иван Петров" not in r.text and "ivan@example.com" not in r.text
    assert "Ромашка" not in r.text and "7707083893" not in r.text


def _lead(db, days_ago: float) -> Lead:
    lead = Lead(
        created_at=NOW - timedelta(days=days_ago),
        upload_id=secrets.token_hex(16),
        material="RESIN",
        qty=2,
        name="Аня",
        phone="+79991234567",
        email="a@example.com",
        comment="позвоните вечером",
        telegram_sent=False,
    )
    db.add(lead)
    db.commit()
    return lead


def test_old_leads_are_anonymized(session):
    """Заявки «цена по запросу» (B44): контакты стираются через тот же срок от даты заявки."""
    old = _lead(session, days_ago=FIVE_YEARS + 1)
    recent = _lead(session, days_ago=FIVE_YEARS - 1)

    dry = anonymize.anonymize_orders(session, now=NOW, dry_run=True)
    assert dry.leads == [old.id]
    session.expire_all()
    assert session.get(Lead, old.id).name == "Аня"

    report = anonymize.anonymize_orders(session, now=NOW)
    assert report.leads == [old.id] and report.to_dict()["leads"] == 1
    session.expire_all()
    o = session.get(Lead, old.id)
    assert o.name == "" and o.phone == "" and o.email is None and o.comment is None
    assert o.anonymized_at is not None and o.material == "RESIN" and o.qty == 2
    assert session.get(Lead, recent.id).name == "Аня"
    # второй прогон ничего не трогает
    assert anonymize.anonymize_orders(session, now=NOW).leads == []
