"""Быстрые заявки (B52): «перезвоните мне» из выходного попапа и «без модели» с фото."""

from datetime import UTC, datetime, timedelta

from conftest import box_stl
from sqlalchemy import select

from app import leads
from app.anonymize import anonymize_orders
from app.config import settings
from app.db import session_factory
from app.models import Event, Lead

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _no_channels(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "owner_email", "")


def test_photo_ext():
    assert leads.photo_ext(JPEG) == "jpg"
    assert leads.photo_ext(PNG) == "png"
    assert leads.photo_ext(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert leads.photo_ext(b"\x00\x00\x00\x18ftypheic....") == "heic"
    assert leads.photo_ext(b"solid cube\n") is None
    assert leads.photo_ext(b"XXXX\x00\x00\x00\x00WEBP") is None  # WEBP без RIFF


def test_clean_page():
    assert leads.clean_page("/upload/abc?x=1#top") == "/upload/abc"
    assert leads.clean_page("https://evil.ru/") is None
    assert leads.clean_page("") is None
    assert len(leads.clean_page("/" + "a" * 500)) == 200


def test_callback_saved_without_channels(client, monkeypatch):
    _no_channels(monkeypatch)
    up = client.post("/api/v1/uploads", files={"file": ("a.stl", box_stl(), "a/b")}).json()
    r = client.post(
        "/api/v1/leads/callback",
        json={
            "phone": "8 999 123-45-67",
            "page": f"/upload/{up['id']}?utm=1",
            "upload_id": up["id"],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["delivered"] is False and body["lead_id"] > 0
    with session_factory()() as s:
        lead = s.scalars(select(Lead)).one()
        ev = s.scalars(select(Event).where(Event.name == "quick_lead")).one()
    assert lead.kind == "callback" and lead.phone.startswith("+7") and lead.name == ""
    assert lead.upload_id == up["id"] and lead.page == f"/upload/{up['id']}"
    assert lead.material is None
    # [ПДн] в events — без телефона
    assert ev.upload_id == up["id"]
    assert ev.props == {
        "kind": "callback",
        "lead_id": lead.id,
        "page": f"/upload/{up['id']}",
        "has_photo": False,
    }


def test_callback_bad_phone_and_bad_upload_id(client, monkeypatch):
    _no_channels(monkeypatch)
    assert client.post("/api/v1/leads/callback", json={"phone": "12"}).status_code == 422
    r = client.post("/api/v1/leads/callback", json={"phone": "89990001122", "upload_id": "../x"})
    assert r.status_code == 201
    with session_factory()() as s:
        assert s.scalars(select(Lead)).one().upload_id is None


def test_callback_goes_to_telegram(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "42")
    monkeypatch.setattr(settings, "owner_email", "")
    sent: list[str] = []
    monkeypatch.setattr(leads, "send_message", lambda chat, text: sent.append(text))
    r = client.post(
        "/api/v1/leads/callback",
        json={"phone": "89990001122", "name": "Оля <b>", "page": "/catalog"},
    )
    assert r.json()["telegram"] is True and r.json()["delivered"] is True
    assert "перезвонить" in sent[0] and "Оля &lt;b&gt;" in sent[0] and "/catalog" in sent[0]


def test_brief_with_photo(client, monkeypatch):
    _no_channels(monkeypatch)
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    r = client.post(
        "/api/v1/leads/brief",
        data={
            "name": " Пётр ",
            "phone": "+7 999 000-11-22",
            "comment": "Сломалась ручка от шкафа, нужна такая же",
            "qty": "4",
            "page": "/request",
        },
        files={"photo": ("IMG_1.jpg", JPEG, "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    lead_id = r.json()["lead_id"]
    with session_factory()() as s:
        lead = s.get(Lead, lead_id)
        ev = s.scalars(select(Event).where(Event.name == "quick_lead")).one()
    assert lead.kind == "brief" and lead.name == "Пётр" and lead.qty == 4
    assert lead.photo == "photo.jpg" and leads.lead_photo_path(lead).read_bytes() == JPEG
    assert ev.props["has_photo"] is True and ev.upload_id is None
    # Фото — только владельцу
    assert client.get(f"/admin/leads/{lead_id}/photo").status_code == 401
    ph = client.get(f"/admin/leads/{lead_id}/photo", auth=("admin", "secret-pass"))
    assert ph.status_code == 200 and ph.content == JPEG
    page = client.get("/admin/leads", auth=("admin", "secret-pass")).text
    assert "без модели" in page and "Сломалась ручка" in page and "Фото ↗" in page


def test_brief_without_photo_and_errors(client, monkeypatch):
    _no_channels(monkeypatch)
    ok = {"name": "Аня", "phone": "89990001122", "comment": "Шестерёнка для миксера"}
    assert client.post("/api/v1/leads/brief", data=ok).status_code == 201
    assert client.post("/api/v1/leads/brief", data={**ok, "comment": "  "}).status_code == 422
    assert client.post("/api/v1/leads/brief", data={**ok, "name": " "}).status_code == 422
    assert client.post("/api/v1/leads/brief", data={**ok, "email": "nope"}).status_code == 422
    assert client.post("/api/v1/leads/brief", data={**ok, "phone": "1"}).status_code == 422
    bad = client.post(
        "/api/v1/leads/brief", data=ok, files={"photo": ("a.jpg", b"not an image", "image/jpeg")}
    )
    assert bad.status_code == 415


def test_brief_photo_too_big(client, monkeypatch):
    _no_channels(monkeypatch)
    monkeypatch.setattr(leads, "PHOTO_MAX_MB", 0)
    r = client.post(
        "/api/v1/leads/brief",
        data={"name": "Аня", "phone": "89990001122", "comment": "Шестерёнка"},
        files={"photo": ("a.png", PNG, "image/png")},
    )
    assert r.status_code == 413


def test_anonymize_deletes_brief_photo(client, monkeypatch):
    _no_channels(monkeypatch)
    monkeypatch.setattr(settings, "anonymize_orders_days", 30)
    r = client.post(
        "/api/v1/leads/brief",
        data={"name": "Аня", "phone": "89990001122", "comment": "Шестерёнка"},
        files={"photo": ("a.png", PNG, "image/png")},
    )
    lead_id = r.json()["lead_id"]
    folder = leads.leads_root() / str(lead_id)
    assert folder.is_dir()
    with session_factory()() as s:
        report = anonymize_orders(s, now=datetime.now(UTC) + timedelta(days=31))
        assert report.leads == [lead_id]
        lead = s.get(Lead, lead_id)
        assert lead.photo is None and lead.phone == "" and lead.comment is None
    assert not folder.exists()
