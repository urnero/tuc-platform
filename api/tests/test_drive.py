"""Файлы заказа в Google Drive (B46): папки, файлы, повтор без дублей, ночная докопировка."""

import json
import re
from urllib.parse import parse_qs

import httpx
import pytest
from conftest import REPO_ROOT, box_stl
from sqlalchemy.orm import Session

from app import drive, export
from app import telegram as tg
from app.config import settings
from app.db import get_engine
from app.models import Order
from app.pricing import reload_pricing
from app.uploads import uploads_root


class FakeDrive:
    """Поддельные OAuth2 (refresh_token) и Drive API v3: папки и файлы в словаре."""

    def __init__(self):
        self.files: dict[str, dict] = {}
        self.uploads: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []
        self.token = "ya29.drive-token"
        self.fail = False  # Google «лежит» → 500

    def _new_id(self) -> str:
        return f"id{len(self.files) + len(self.uploads) + 1}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["refresh_token"]
            assert form["refresh_token"] == ["1//refresh"]
            return httpx.Response(200, json={"access_token": self.token, "expires_in": 3599})
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": {"message": "bad token"}})
        if self.fail:
            return httpx.Response(500, json={"error": {"message": "backend error"}})
        path, params = request.url.path, dict(request.url.params)
        if path == "/drive/v3/files" and request.method == "GET":
            q = params["q"]
            parent = re.search(r"'([^']+)' in parents", q).group(1)
            name = re.search(r"name = '((?:[^'\\]|\\.)*)'", q)
            found = [
                {"id": fid, "name": f["name"], "webViewLink": f"https://drive/{fid}"}
                for fid, f in self.files.items()
                if parent in f["parents"]
                and (name is None or f["name"] == name.group(1).replace("\\'", "'"))
                and ("mimeType" not in q or f["mime"] == drive.FOLDER_MIME)
            ]
            return httpx.Response(200, json={"files": found})
        if path == "/drive/v3/files" and request.method == "POST":
            body = json.loads(request.content)
            fid = self._new_id()
            self.files[fid] = {**body, "mime": body["mimeType"]}
            return httpx.Response(200, json={"id": fid, "webViewLink": f"https://drive/{fid}"})
        if path == "/upload/drive/v3/files" and request.method == "POST":
            assert params["uploadType"] == "resumable"
            uid = f"up{len(self.uploads) + 1}"
            self.uploads[uid] = json.loads(request.content)
            loc = f"https://www.googleapis.com/upload/drive/v3/files?upload_id={uid}"
            return httpx.Response(200, headers={"location": loc})
        if path == "/upload/drive/v3/files" and request.method == "PUT":
            meta = self.uploads.pop(params["upload_id"])
            fid = self._new_id()
            self.files[fid] = {**meta, "mime": "file", "data": request.content}
            return httpx.Response(200, json={"id": fid})
        return httpx.Response(404, json={"error": {"message": f"нет {path}"}})

    def by_name(self, name: str) -> list[dict]:
        return [dict(f, id=fid) for fid, f in self.files.items() if f["name"] == name]

    def children(self, folder_id: str) -> dict[str, dict]:
        return {f["name"]: dict(f, id=fid) for fid, f in self.files.items()
                if folder_id in f["parents"]}


@pytest.fixture
def pricing_file(monkeypatch):
    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    yield
    reload_pricing()


@pytest.fixture
def gdrive(monkeypatch):
    fake = FakeDrive()
    monkeypatch.setattr(drive, "TRANSPORT", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(settings, "google_drive_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_drive_client_secret", "secret")
    monkeypatch.setattr(settings, "google_drive_refresh_token", "1//refresh")
    monkeypatch.setattr(settings, "google_drive_folder_id", "")
    monkeypatch.setattr(settings, "google_sa_json_path", None)
    return fake


def upload(client, name="box.stl") -> dict:
    r = client.post("/api/v1/uploads", files={"file": (name, box_stl(), "model/stl")})
    assert r.status_code == 201, r.text
    return r.json()


def make_order(client, upload_id: str | None = None, name="Мария") -> dict:
    up_id = upload_id or upload(client)["id"]
    client.post(f"/api/v1/uploads/{up_id}/slice", json={"material": "PLA"})
    quote = client.post(
        f"/api/v1/uploads/{up_id}/quote",
        json={"material": "PLA", "qty": 2, "delivery": "pickup"},
    ).json()
    r = client.post(
        "/api/v1/orders",
        json={"quote_id": quote["id"], "name": name, "phone": "8 999 123-45-67",
              "comment": "Синий, если есть", "consent": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


def order_row(order_id: int) -> Order:
    with Session(get_engine()) as s:
        o = s.get(Order, order_id)
        s.expunge(o)
        return o


def order_folder(fake: FakeDrive, number: str) -> dict:
    [folder] = [dict(f, id=fid) for fid, f in fake.files.items()
                if f["name"].startswith(number + " — ")]
    return folder


def test_new_order_copied_to_month_folder(client, fake_slicer, pricing_file, gdrive):
    o = make_order(client)
    [root] = gdrive.by_name("Заказы сайта")
    assert root["parents"] == ["root"]
    [month] = [f for f in gdrive.children(root["id"]).values()]
    assert re.fullmatch(r"\d{4}-\d{2}", month["name"])
    [folder] = gdrive.children(month["id"]).values()
    assert folder["name"] == f"{o['number']} — Мария"
    files = gdrive.children(folder["id"])
    assert set(files) == {"box.stl", "заказ.txt"}
    assert files["box.stl"]["data"] == box_stl()
    text = files["заказ.txt"]["data"].decode()
    assert f"Заказ {o['number']}" in text and "PLA" in text and "Синий, если есть" in text
    assert "999" not in text  # телефона клиента в файле нет
    url = f"https://drive/{folder['id']}"
    assert order_row(o["id"]).drive_folder_url == url
    with Session(get_engine()) as s:
        row = dict(zip(export.COLUMNS, export.order_rows(s, [s.get(Order, o["id"])])[0],
                       strict=True))
    assert row["drive_folder_url"] == url


def test_second_order_reuses_root_and_month(client, fake_slicer, pricing_file, gdrive):
    make_order(client, name="Мария")
    make_order(client, name="Пётр")
    assert len(gdrive.by_name("Заказы сайта")) == 1
    [root] = gdrive.by_name("Заказы сайта")
    [month] = gdrive.children(root["id"]).values()
    assert len(gdrive.children(month["id"])) == 2


def test_repeat_copy_does_not_duplicate(client, fake_slicer, pricing_file, gdrive):
    o = make_order(client)
    before = len(gdrive.files)
    with Session(get_engine()) as s:
        drive.copy_order(s, o["id"])
    assert len(gdrive.files) == before


def test_processed_model_comes_with_its_source(client, fake_slicer, pricing_file, gdrive):
    """Раскрашенная/с надписью модель — новая загрузка с parent_id: в папку идут обе."""
    src = upload(client, "orig.stl")
    painted = upload(client, "orig (цвета).stl")
    meta_path = uploads_root() / painted["id"] / "meta.json"
    meta = json.loads(meta_path.read_text("utf-8"))
    meta.update(source="paint", paint={"parent_id": src["id"], "parent_name": "orig.stl"})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    o = make_order(client, upload_id=painted["id"])
    files = gdrive.children(order_folder(gdrive, o["number"])["id"])
    assert set(files) == {"orig (цвета).stl", "исходник — orig.stl", "заказ.txt"}


def test_owner_gets_telegram_link(client, fake_slicer, pricing_file, gdrive, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(tg, "telegram_enabled", lambda: True)
    monkeypatch.setattr(tg, "send_message", lambda chat, text, kb=None: sent.append(text) or True)
    o = make_order(client)
    drive_msgs = [t for t in sent if t.startswith("📁")]
    assert len(drive_msgs) == 1
    assert o["number"] in drive_msgs[0] and "https://drive/" in drive_msgs[0]


def test_disabled_without_keys(client, fake_slicer, pricing_file, monkeypatch):
    monkeypatch.setattr(settings, "google_drive_refresh_token", "")
    monkeypatch.setattr(settings, "google_drive_folder_id", "")
    assert drive.mode() is None
    o = make_order(client)
    assert order_row(o["id"]).drive_folder_url is None
    assert drive.backfill_job() is None


def test_service_account_needs_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "google_drive_refresh_token", "")
    monkeypatch.setattr(settings, "google_sa_json_path", tmp_path / "sa.json")
    monkeypatch.setattr(settings, "google_drive_folder_id", "")
    assert drive.mode() is None  # SA без папки общего диска писать некуда
    monkeypatch.setattr(settings, "google_drive_folder_id", "0AbcShared")
    assert drive.mode() == "sa"


def test_google_error_keeps_order_and_backfill_fixes(client, fake_slicer, pricing_file, gdrive):
    gdrive.fail = True
    o = make_order(client)  # заказ оформлен, хоть Google и не ответил
    assert order_row(o["id"]).drive_folder_url is None
    gdrive.fail = False
    assert drive.backfill_job() == {"copied": 1, "failed": 0}
    assert order_row(o["id"]).drive_folder_url
    assert drive.backfill_job() == {"copied": 0, "failed": 0}  # второй раз — нечего


def test_backfill_skips_cancelled(client, fake_slicer, pricing_file, gdrive):
    gdrive.fail = True
    o = make_order(client)
    with Session(get_engine()) as s:
        s.get(Order, o["id"]).status = "cancelled"
        s.commit()
    gdrive.fail = False
    assert drive.backfill_job() == {"copied": 0, "failed": 0}


def test_storage_quota_hint():
    r = httpx.Response(403, text='{"error":{"errors":[{"reason":"storageQuotaExceeded"}]}}')
    with pytest.raises(drive.DriveError, match="общем диске"):
        drive._check(r, "Загрузка")


def test_names_are_safe():
    assert drive._clean("a/b\nc") == "a_b_c"
    assert drive._q("O'Brien \\") == "O\\'Brien \\\\"
