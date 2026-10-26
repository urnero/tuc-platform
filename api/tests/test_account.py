"""Кабинет клиента (B32): вход по коду из письма, история заказов; письма (app/mailer.py)."""

import re
import shutil
import smtplib
from datetime import UTC, datetime, timedelta

import pytest
from conftest import REPO_ROOT
from sqlalchemy import select, update
from test_orders import GOOD, _quote

from app import account, mailer
from app.config import settings
from app.models import ClientSession, Event, LoginCode
from app.pricing import reload_pricing
from app.uploads import uploads_root

EMAIL = "Ivan@Example.ru"  # с заглавными: кабинет не различает регистр


@pytest.fixture
def pricing_file(monkeypatch):
    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    yield
    reload_pricing()


@pytest.fixture
def mailbox(monkeypatch):
    """Вместо SMTP — список отправленных писем; `mailbox.code()` — код из последнего."""
    sent: list[tuple[str, str, str]] = []

    def fake_send(to, subject, text):
        sent.append((to, subject, text))
        return True

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.ru")
    monkeypatch.setattr(account, "send_mail", fake_send)

    class Box:
        messages = sent

        @staticmethod
        def code() -> str:
            return re.search(r"\b(\d{6})\b", sent[-1][2]).group(1)

    return Box


def _login(client, mailbox, email=EMAIL) -> dict:
    r = client.post("/api/v1/account/login", json={"email": email})
    assert r.status_code == 202, r.text
    body = {"email": email, "code": mailbox.code()}
    r = client.post("/api/v1/account/login/confirm", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _order(client, email=EMAIL, **extra) -> dict:
    quote = _quote(client)
    body = {**GOOD, "quote_id": quote["id"], "email": email, **extra}
    r = client.post("/api/v1/orders", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- вход ---------------------------------------------------------------------


def test_login_without_smtp_503(client):
    assert settings.smtp_host == ""
    r = client.post("/api/v1/account/login", json={"email": EMAIL})
    assert r.status_code == 503
    assert "не настроена" in r.json()["detail"]


def test_login_bad_email_422(client, mailbox):
    r = client.post("/api/v1/account/login", json={"email": "не почта"})
    assert r.status_code == 422
    assert mailbox.messages == []


def test_login_sends_code_and_sets_cookie(client, mailbox, db):
    r = client.post("/api/v1/account/login", json={"email": f"  {EMAIL} "})
    assert r.status_code == 202
    assert r.json() == {"sent": True, "email": "ivan@example.ru", "expires_in_min": 15}
    to, subject, text = mailbox.messages[-1]
    assert to == "ivan@example.ru"
    code = mailbox.code()
    assert code in subject and "15 минут" in text and "/account" in text
    # в БД — только sha256 кода
    with db.connect() as conn:
        row = conn.execute(select(LoginCode.email, LoginCode.code_hash, LoginCode.attempts)).one()
    assert row[0] == "ivan@example.ru" and row[1] != code and len(row[1]) == 64 and row[2] == 0

    spaced = f" {code[:3]} {code[3:]} "  # пробелы из письма не мешают
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": spaced})
    assert r.status_code == 200, r.text
    assert r.json() == {"email": "ivan@example.ru", "orders_count": 0, "contacts": None}
    cookie = r.headers["set-cookie"]
    assert "tuc_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie  # SITE_URL по умолчанию http
    assert client.cookies.get("tuc_session")

    assert client.get("/api/v1/account").status_code == 200
    # вход записан в events
    with db.connect() as conn:
        names = conn.execute(select(Event.name)).scalars().all()
    assert "account_login" in names


def test_cookie_secure_on_https(client, mailbox, monkeypatch):
    monkeypatch.setattr(settings, "site_url", "https://tuc.example.ru")
    client.post("/api/v1/account/login", json={"email": EMAIL})
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": mailbox.code()})
    assert "Secure" in r.headers["set-cookie"]


def test_confirm_wrong_code_counts_attempts(client, mailbox, db):
    client.post("/api/v1/account/login", json={"email": EMAIL})
    code = mailbox.code()
    wrong = "000000" if code != "000000" else "111111"
    for left in (4, 3, 2, 1):
        r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": wrong})
        assert r.status_code == 400 and f"Осталось попыток: {left}" in r.json()["detail"]
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": wrong})
    assert r.status_code == 400 and "Запросите новый" in r.json()["detail"]
    # после пяти промахов даже верный код не подходит
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": code})
    assert r.status_code == 400 and "Слишком много" in r.json()["detail"]
    assert "tuc_session" not in client.cookies


def test_confirm_code_is_single_use(client, mailbox):
    client.post("/api/v1/account/login", json={"email": EMAIL})
    code = mailbox.code()
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": code})
    assert r.status_code == 200
    client.cookies.clear()
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": code})
    assert r.status_code == 400 and "не запрошен или устарел" in r.json()["detail"]


def test_confirm_expired_code(client, mailbox, db):
    client.post("/api/v1/account/login", json={"email": EMAIL})
    code = mailbox.code()
    with db.begin() as conn:
        conn.execute(update(LoginCode).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": code})
    assert r.status_code == 400 and "устарел" in r.json()["detail"]


def test_confirm_not_six_digits_422(client, mailbox):
    client.post("/api/v1/account/login", json={"email": EMAIL})
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": "12ab"})
    assert r.status_code == 422


def test_resend_not_sooner_than_minute(client, mailbox, db):
    assert client.post("/api/v1/account/login", json={"email": EMAIL}).status_code == 202
    r = client.post("/api/v1/account/login", json={"email": EMAIL})
    assert r.status_code == 429 and r.headers["Retry-After"] == "60"
    assert len(mailbox.messages) == 1
    # минута прошла — новый код, старый неиспользованный остаётся до срока, но работает только новый
    with db.begin() as conn:
        conn.execute(update(LoginCode).values(created_at=datetime.now(UTC) - timedelta(seconds=61)))
    old = mailbox.code()
    assert client.post("/api/v1/account/login", json={"email": EMAIL}).status_code == 202
    new = mailbox.code()
    if old != new:
        r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": old})
        assert r.status_code == 400
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": new})
    assert r.status_code == 200


def test_login_mail_failure_503_and_no_code_left(client, mailbox, monkeypatch, db):
    monkeypatch.setattr(account, "send_mail", lambda *a: False)
    r = client.post("/api/v1/account/login", json={"email": EMAIL})
    assert r.status_code == 503
    with db.connect() as conn:
        assert conn.execute(select(LoginCode.id)).all() == []


def test_login_rate_limited_per_ip(client, mailbox, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_min", 2)
    for i, email in enumerate(["a@x.ru", "b@x.ru"]):
        assert client.post("/api/v1/account/login", json={"email": email}).status_code == 202, i
    r = client.post("/api/v1/account/login", json={"email": "c@x.ru"})
    assert r.status_code == 429
    r = client.post("/api/v1/account/login/confirm", json={"email": "a@x.ru", "code": "123456"})
    assert r.status_code == 429  # ввод кода считается в том же окне — подбирать нельзя


# --- кабинет ------------------------------------------------------------------


def test_account_requires_login(client):
    assert client.get("/api/v1/account").status_code == 401
    assert client.get("/api/v1/account/orders").status_code == 401
    client.cookies.set("tuc_session", "0" * 32)  # выдуманный token
    assert client.get("/api/v1/account").status_code == 401


def test_orders_history_by_email_any_case(client, mailbox, pricing_file, fake_slicer):
    """Заказы, оформленные до входа (и с другим регистром адреса), видны в кабинете."""
    first = _order(client, email="ivan@example.ru", comment="первый")
    second = _order(client, email="IVAN@EXAMPLE.RU", address="")
    _order(client, email="other@example.ru")
    info = _login(client, mailbox)
    assert info["orders_count"] == 2
    assert info["contacts"] == {"name": "Иван", "phone": "+79991234567", "address": ""}

    r = client.get("/api/v1/account/orders")
    assert r.status_code == 200
    orders = r.json()["orders"]
    assert [o["id"] for o in orders] == [second["id"], first["id"]]  # новые сверху
    o = orders[1]
    assert o["token"] == first["token"] and o["comment"] == "первый"
    assert o["material"] == "PLA" and o["qty"] == 1 and o["delivery"] == "pickup"
    assert o["payment"]["enabled"] is False
    assert o["can_repeat"] is True


def test_can_repeat_false_when_model_deleted(client, mailbox, pricing_file, fake_slicer):
    order = _order(client)
    shutil.rmtree(uploads_root() / order["upload_id"])  # как app/cleanup.py через год
    _login(client, mailbox)
    orders = client.get("/api/v1/account/orders").json()["orders"]
    assert orders[0]["can_repeat"] is False


def test_order_without_email_gets_session_email(client, mailbox, pricing_file, fake_slicer):
    """Клиент вошёл в кабинет и оставил e-mail в форме пустым — заказ всё равно его."""
    _login(client, mailbox)
    order = _order(client, email="")
    assert order["email"] == "ivan@example.ru"
    assert client.get("/api/v1/account").json()["orders_count"] == 1
    # а явно указанный адрес важнее сессии
    order2 = _order(client, email="other@example.ru")
    assert order2["email"] == "other@example.ru"


def test_logout(client, mailbox, db):
    _login(client, mailbox)
    r = client.post("/api/v1/account/logout")
    assert r.status_code == 200
    assert client.get("/api/v1/account").status_code == 401
    with db.connect() as conn:
        assert conn.execute(select(ClientSession.id)).all() == []


def test_expired_session_is_rejected(client, mailbox, db):
    _login(client, mailbox)
    with db.begin() as conn:
        conn.execute(update(ClientSession).values(expires_at=datetime.now(UTC) - timedelta(days=1)))
    assert client.get("/api/v1/account").status_code == 401


# --- письма (app/mailer.py) ---------------------------------------------------


class FakeSMTP:
    """Запоминает, что с ним делали. Подменяет smtplib.SMTP_SSL / SMTP."""

    calls: list = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.calls.append(("connect", host, port))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        FakeSMTP.calls.append(("quit",))

    def starttls(self):
        FakeSMTP.calls.append(("starttls",))

    def login(self, user, password):
        FakeSMTP.calls.append(("login", user, password))

    def send_message(self, msg):
        FakeSMTP.calls.append(
            ("send", msg["From"], msg["To"], msg["Subject"], msg.get_content())
        )


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.calls = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.ru")
    monkeypatch.setattr(settings, "smtp_port", 465)
    monkeypatch.setattr(settings, "smtp_user", "noreply@example.ru")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(settings, "smtp_from", "")
    monkeypatch.setattr(settings, "smtp_ssl", True)
    return FakeSMTP


def test_send_mail_ssl(smtp):
    assert mailer.send_mail("ivan@example.ru", "Тема", "Текст\n") is True
    assert smtp.calls == [
        ("connect", "smtp.example.ru", 465),
        ("login", "noreply@example.ru", "secret"),
        ("send", "noreply@example.ru", "ivan@example.ru", "Тема", "Текст\n"),
        ("quit",),
    ]


def test_send_mail_starttls_and_from(smtp, monkeypatch):
    monkeypatch.setattr(settings, "smtp_ssl", False)
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_from", "ТУЦ <hello@example.ru>")
    assert mailer.send_mail("ivan@example.ru", "Тема", "Текст") is True
    assert smtp.calls[0] == ("connect", "smtp.example.ru", 587)
    assert smtp.calls[1] == ("starttls",)
    assert smtp.calls[3][1] == "ТУЦ <hello@example.ru>"


def test_send_mail_smtp_error_returns_false(smtp, monkeypatch):
    def boom(self, msg):
        raise smtplib.SMTPAuthenticationError(535, b"bad password")

    monkeypatch.setattr(FakeSMTP, "send_message", boom)
    assert mailer.send_mail("ivan@example.ru", "Тема", "Текст") is False


def test_send_mail_disabled_and_log_mode(monkeypatch, caplog):
    monkeypatch.setattr(settings, "smtp_host", "")
    assert mailer.mail_enabled() is False
    assert mailer.send_mail("ivan@example.ru", "Тема", "Текст") is False
    monkeypatch.setattr(settings, "smtp_host", "log")
    with caplog.at_level("INFO", logger="app.mailer"):
        assert mailer.send_mail("ivan@example.ru", "Тема", "Код 123456") is True
    assert "Код 123456" in caplog.text


def test_login_in_log_mode_works_without_smtp(client, monkeypatch, caplog):
    """SMTP_HOST=log: код виден в логе api — так владелец проверяет кабинет на ноутбуке."""
    monkeypatch.setattr(settings, "smtp_host", "log")
    with caplog.at_level("INFO", logger="app.mailer"):
        assert client.post("/api/v1/account/login", json={"email": EMAIL}).status_code == 202
    code = re.search(r"кабинет: (\d{6})", caplog.text).group(1)
    r = client.post("/api/v1/account/login/confirm", json={"email": EMAIL, "code": code})
    assert r.status_code == 200
