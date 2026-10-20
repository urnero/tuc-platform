"""Экспорт заказов в Google-таблицу (B11): токен по ключу сервисного аккаунта, лист, строки."""

import asyncio
import json
from urllib.parse import parse_qs, unquote

import httpx
import jwt
import pytest
from conftest import REPO_ROOT, box_stl
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session

from app import export, sheets, worker
from app.config import settings
from app.db import get_engine
from app.models import Payment, utcnow
from app.pricing import reload_pricing

SHEET_ID = "1AbCdEf"


@pytest.fixture
def pricing_file(monkeypatch):
    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    yield
    reload_pricing()


class FakeGoogle:
    """Поддельные OAuth2 и Sheets API v4: проверяет подпись JWT, хранит листы и их значения."""

    def __init__(self, public_key_pem: str, tabs: list[str]):
        self.public_key_pem = public_key_pem
        self.tabs = list(tabs)
        self.values: dict[str, list[list]] = {}
        self.requests: list[httpx.Request] = []
        self.token = "ya29.fake-token"
        self.forbid = False  # таблица не расшарена → 403

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            form = parse_qs(request.content.decode())
            claims = jwt.decode(
                form["assertion"][0],
                self.public_key_pem,
                algorithms=["RS256"],
                audience=sheets.TOKEN_URL,
            )
            assert claims["iss"] == "tuc-export@example.iam.gserviceaccount.com"
            assert claims["scope"] == sheets.SCOPE
            return httpx.Response(200, json={"access_token": self.token, "expires_in": 3599})

        assert request.url.host == "sheets.googleapis.com"
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": {"message": "bad token"}})
        if self.forbid:
            return httpx.Response(403, json={"error": {"message": "caller has no permission"}})
        path = unquote(request.url.path)
        prefix = f"/v4/spreadsheets/{SHEET_ID}"
        if not path.startswith(prefix):
            return httpx.Response(404, json={"error": {"message": "entity was not found"}})
        rest = path[len(prefix):]

        if rest == "" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "spreadsheetUrl": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit",
                    "sheets": [{"properties": {"title": t}} for t in self.tabs],
                },
            )
        if rest == ":batchUpdate":
            for req in json.loads(request.content)["requests"]:
                self.tabs.append(req["addSheet"]["properties"]["title"])
            return httpx.Response(200, json={"replies": [{}]})
        if rest.startswith("/values/"):
            rng = rest[len("/values/"):]
            clear = rng.endswith(":clear")
            tab = rng.removesuffix(":clear").strip("'")
            if tab not in self.tabs:
                return httpx.Response(400, json={"error": {"message": f"bad range: {tab}"}})
            if clear:
                self.values[tab] = []
                return httpx.Response(200, json={"clearedRange": rng})
            body = json.loads(request.content)
            assert request.url.params["valueInputOption"] == "RAW"
            self.values[tab] = body["values"]
            return httpx.Response(200, json={"updatedRows": len(body["values"])})
        return httpx.Response(404, json={"error": {"message": f"unknown {request.method} {path}"}})


@pytest.fixture
def google(tmp_path, monkeypatch):
    """Ключ сервисного аккаунта во временной папке + поддельный Google вместо сети."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    sa_path = tmp_path / "google-sa.json"
    sa_path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "client_email": "tuc-export@example.iam.gserviceaccount.com",
                "private_key": private_pem,
                "token_uri": sheets.TOKEN_URL,
            }
        ),
        encoding="utf-8",
    )
    fake = FakeGoogle(public_pem, tabs=["Учёт", "Материалы"])
    monkeypatch.setattr(sheets, "TRANSPORT", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(settings, "google_sa_json_path", sa_path)
    monkeypatch.setattr(settings, "google_sheet_id", SHEET_ID)
    monkeypatch.setattr(settings, "google_sheet_tab", "Заказы (сайт)")
    return fake


def make_order(client, name="Мария", qty=2) -> dict:
    up = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")}).json()
    client.post(f"/api/v1/uploads/{up['id']}/slice", json={"material": "PLA"})
    quote = client.post(
        f"/api/v1/uploads/{up['id']}/quote",
        json={"material": "PLA", "qty": qty, "delivery": "pickup"},
    ).json()
    r = client.post(
        "/api/v1/orders",
        json={"quote_id": quote["id"], "name": name, "phone": "8 999 123-45-67", "consent": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_export_writes_header_and_rows(client, fake_slicer, pricing_file, google):
    o1 = make_order(client, "Мария", qty=2)
    o2 = make_order(client, "Пётр", qty=1)
    with Session(get_engine()) as db:
        # у второго заказа есть успешная онлайн-оплата
        db.add(
            Payment(
                order_id=o2["id"], yookassa_id="pay-1", idempotence_key="k1", status="succeeded",
                amount=o2["total"], paid_at=utcnow(),
            )
        )
        db.commit()
        result = sheets.export_orders(db)

    assert result["rows"] == 2
    assert result["tab"] == "Заказы (сайт)"
    assert result["url"].endswith(f"/d/{SHEET_ID}/edit")
    # лист создан (его не было), остальные листы на месте
    assert google.tabs == ["Учёт", "Материалы", "Заказы (сайт)"]
    rows = google.values["Заказы (сайт)"]
    assert rows[0] == export.COLUMNS
    assert len(rows) == 3
    first = dict(zip(export.COLUMNS, rows[1], strict=True))
    assert first["number"] == f"ТУЦ-{o1['id']}"
    assert first["customer_name"] == "Мария"
    assert first["phone"] == "+79991234567"  # текст, «+» на месте
    assert first["qty"] == 2 and first["total"] == o1["total"]
    assert first["status_label"] == "принят" and first["paid_msk"] == ""
    second = dict(zip(export.COLUMNS, rows[2], strict=True))
    assert second["customer_name"] == "Пётр" and second["paid_msk"] != ""
    # порядок вызовов: токен → метаданные → создать лист → очистить → записать
    methods = [
        (r.method, r.url.host, unquote(r.url.path).rsplit("/", 1)[-1]) for r in google.requests
    ]
    assert methods == [
        ("POST", "oauth2.googleapis.com", "token"),
        ("GET", "sheets.googleapis.com", SHEET_ID),
        ("POST", "sheets.googleapis.com", f"{SHEET_ID}:batchUpdate"),
        ("POST", "sheets.googleapis.com", "'Заказы (сайт)':clear"),
        ("PUT", "sheets.googleapis.com", "'Заказы (сайт)'"),
    ]


def test_export_rewrites_existing_tab(client, fake_slicer, pricing_file, google):
    google.tabs.append("Заказы (сайт)")
    google.values["Заказы (сайт)"] = [["старое"], ["содержимое"]]
    make_order(client)
    with Session(get_engine()) as db:
        sheets.export_orders(db)
    assert google.tabs.count("Заказы (сайт)") == 1  # второй раз не создаём
    assert google.values["Заказы (сайт)"][0] == export.COLUMNS
    assert len(google.values["Заказы (сайт)"]) == 2


def test_export_matches_admin_csv(client, fake_slicer, pricing_file, google, monkeypatch):
    """В таблице и в CSV админки — одни и те же колонки и значения."""
    monkeypatch.setattr(settings, "admin_password", "secret")
    make_order(client)
    with Session(get_engine()) as db:
        sheets.export_orders(db)
    csv_text = client.get("/admin/orders.csv", auth=("admin", "secret")).text.lstrip("﻿")
    header, line = csv_text.splitlines()[:2]
    assert header.split(";") == export.COLUMNS
    assert line.split(";") == [str(v) for v in google.values["Заказы (сайт)"][1]]


def test_export_without_orders(db, google):
    with Session(get_engine()) as s:
        assert sheets.export_orders(s)["rows"] == 0
    assert google.values["Заказы (сайт)"] == [export.COLUMNS]


def test_disabled_without_keys(db, monkeypatch):
    monkeypatch.setattr(settings, "google_sa_json_path", None)
    monkeypatch.setattr(settings, "google_sheet_id", "")
    assert not sheets.enabled()
    assert sheets.export_orders_job() is None  # cron и CLI молча пропускают
    assert sheets.main() == 0


def test_forbidden_gives_hint(db, google):
    google.forbid = True
    with Session(get_engine()) as s, pytest.raises(sheets.SheetsError, match="Расшарьте таблицу"):
        sheets.export_orders(s)


def test_wrong_sheet_id(db, google, monkeypatch):
    monkeypatch.setattr(settings, "google_sheet_id", "nope")
    with Session(get_engine()) as s, pytest.raises(sheets.SheetsError, match="GOOGLE_SHEET_ID"):
        sheets.export_orders(s)


def test_missing_key_file(db, google, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "google_sa_json_path", tmp_path / "no-such.json")
    with Session(get_engine()) as s, pytest.raises(sheets.SheetsError, match="Нет файла ключа"):
        sheets.export_orders(s)


def test_cli_and_cron(db, google, capsys):
    """`python -m app.sheets` и задача worker зовут один и тот же экспорт."""
    assert sheets.main() == 0
    assert "0 заказов" in capsys.readouterr().out
    assert asyncio.run(worker.export_sheet({}))["rows"] == 0
    assert "cron:export_sheet" in [c.name for c in worker.WorkerSettings.cron_jobs]


def test_empty_path_in_env_means_disabled(monkeypatch):
    """`GOOGLE_SA_JSON_PATH=` в .env — экспорт выключен, а не путь «.»."""
    from app.config import Settings

    monkeypatch.setenv("GOOGLE_SA_JSON_PATH", "")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "x")
    assert Settings().google_sa_json_path is None
