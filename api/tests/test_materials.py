"""Справочник материалов (B44) и заявка «цена по запросу» для смол."""

import pytest
import yaml
from conftest import REPO_ROOT, box_stl
from sqlalchemy import select

from app import leads, materials
from app.config import settings
from app.db import session_factory
from app.models import Event, Lead
from app.pricing import parse_pricing
from app.slicer import SlicerError, check_material

MATERIALS_YAML = REPO_ROOT / "config" / "materials.yaml"
PRICING_YAML = REPO_ROOT / "config" / "pricing.yaml"


# --- справочник согласован с профилями и ценами -------------------------------------


def test_repo_materials_consistent():
    """Каждый FDM-материал: профиль слайсера + цена. Смолы — без цены (по запросу)."""
    items = materials.load_materials(MATERIALS_YAML)
    pricing = parse_pricing(yaml.safe_load(PRICING_YAML.read_text("utf-8")))
    fdm = [m for m in items.values() if m.tech == "FDM"]
    assert {"PLA", "PETG", "ABS", "TPU", "PA", "PC", "PETG-CF", "PA-CF"} <= {m.key for m in fdm}
    assert "ASA" not in items  # ASA студия не печатает (docs/PRINTERS.md)
    for m in fdm:
        assert (REPO_ROOT / "profiles" / "filament" / f"{m.key}.ini").is_file(), m.key
        assert m.key in pricing.materials, m.key
        assert m.hint and m.tagline and m.colors and m.max_mm, m.key
    sla = [m for m in items.values() if m.tech == "SLA"]
    assert len(sla) >= 3
    for m in sla:
        assert m.on_request and m.key not in pricing.materials


def test_enclosure_materials_fit_p1s():
    """ABS, PC, PA, *-CF печатаются только на P1S/Q1 Pro → не больше 256 мм."""
    items = materials.load_materials(MATERIALS_YAML)
    for key in ("ABS", "PC", "PA", "PA-CF"):
        assert items[key].needs_enclosure
        assert max(items[key].max_mm) <= 256


def test_profiles_have_core_keys():
    for path in (REPO_ROOT / "profiles" / "filament").glob("*.ini"):
        text = path.read_text("utf-8")
        for key in ("filament_type", "filament_density", "temperature", "bed_temperature"):
            assert f"\n{key} = " in text, f"{path.name}: нет {key}"


def test_sliceable_and_on_request():
    assert materials.sliceable()[:3] == ("PLA", "PETG", "ABS")
    assert "RESIN" in materials.on_request()
    assert "RESIN" not in materials.sliceable()


def test_check_material_messages():
    check_material("PETG-CF")
    with pytest.raises(SlicerError, match="заявку"):
        check_material("RESIN")
    with pytest.raises(SlicerError, match="Материал: PLA"):
        check_material("ASA")


def test_disabled_material_hidden(tmp_path, monkeypatch):
    p = tmp_path / "m.yaml"
    p.write_text(
        "materials:\n"
        "  PLA: {tech: FDM, name: PLA}\n"
        "  PC: {tech: FDM, name: PC, enabled: false}\n"
        "  RESIN: {tech: SLA, name: Смола}\n",
        "utf-8",
    )
    monkeypatch.setattr(settings, "materials_path", p)
    assert materials.sliceable() == ("PLA",)
    assert materials.on_request() == ("RESIN",)


def test_no_yaml_falls_back_to_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "materials_path", tmp_path / "нет.yaml")
    monkeypatch.setattr(settings, "profiles_dir", REPO_ROOT / "profiles")
    assert "PLA" in materials.sliceable() and "PA-CF" in materials.sliceable()


@pytest.mark.parametrize(
    "raw, msg",
    [
        ({}, "раздел materials"),
        ({"materials": {"X": {"tech": "DLP"}}}, "tech"),
        ({"materials": {"X": {"tech": "FDM", "max_mm": [1, 2]}}}, "max_mm"),
        ({"materials": {"X": {"tech": "FDM", "colors": "белый"}}}, "colors"),
    ],
)
def test_parse_errors(raw, msg):
    with pytest.raises(materials.MaterialsError, match=msg):
        materials.parse_materials(raw)


def test_fits_with_rotation():
    assert materials.fits((200, 100, 120), (218, 123, 200))  # повернём на бок
    assert not materials.fits((220, 100, 50), (218, 123, 200))


# --- API -----------------------------------------------------------------------------


def test_materials_endpoint(client):
    d = client.get("/api/v1/materials").json()
    assert d["materials"][:3] == ["PLA", "PETG", "ABS"]
    assert "TPU" in d["materials"] and "RESIN" not in d["materials"]
    assert d["on_request"] == ["RESIN", "RESIN-TOUGH", "RESIN-NYLON"]
    pc = next(i for i in d["items"] if i["key"] == "PC")
    assert pc["needs_enclosure"] and pc["heat_c"] == 110 and pc["max_mm"] == [256, 256, 256]
    assert next(i for i in d["items"] if i["key"] == "RESIN")["on_request"] is True


def test_slice_resin_is_422(client, fake_slicer):
    up = client.post("/api/v1/uploads", files={"file": ("a.stl", box_stl(), "application/sla")})
    r = client.post(f"/api/v1/uploads/{up.json()['id']}/slice", json={"material": "RESIN"})
    assert r.status_code == 422 and "заявку" in r.json()["detail"]


def test_slice_new_material(client, fake_slicer):
    up = client.post("/api/v1/uploads", files={"file": ("a.stl", box_stl(), "application/sla")})
    r = client.post(f"/api/v1/uploads/{up.json()['id']}/slice", json={"material": "PETG-CF"})
    assert r.status_code == 202 and r.json()["status"] == "done"


def _upload(client) -> str:
    r = client.post("/api/v1/uploads", files={"file": ("mini.stl", box_stl(), "a/b")})
    return r.json()["id"]


def test_lead_without_telegram_saved_in_leads(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    uid = _upload(client)
    r = client.post(
        f"/api/v1/uploads/{uid}/request",
        json={
            "material": "resin",
            "qty": 3,
            "name": " Аня ",
            "phone": "8 999 123-45-67",
            "email": "a@example.com",
            "comment": "срочно",
        },
    )
    assert r.status_code == 201 and r.json() == {"ok": True, "telegram": False}
    with session_factory()() as s:
        lead = s.scalars(select(Lead)).one()
        ev = s.scalars(select(Event).where(Event.name == "material_request")).one()
    assert lead.upload_id == uid and lead.material == "RESIN" and lead.qty == 3
    assert lead.name == "Аня" and lead.phone.startswith("+7") and lead.email == "a@example.com"
    assert lead.comment == "срочно" and lead.telegram_sent is False
    # [ПДн] в events — только факт заявки, без контактов клиента
    assert ev.upload_id == uid
    assert ev.props == {"material": "RESIN", "qty": 3, "lead_id": lead.id}


def test_admin_lists_leads(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    uid = _upload(client)
    client.post(
        f"/api/v1/uploads/{uid}/request",
        json={"material": "RESIN", "name": "Вера <i>", "phone": "89990001122"},
    )
    assert client.get("/admin/leads").status_code == 401
    r = client.get("/admin/leads", auth=("admin", "secret-pass"))
    assert r.status_code == 200
    assert "Вера &lt;i&gt;" in r.text and "Смола стандартная" in r.text
    assert f"/upload/{uid}" in r.text and "Бот не настроен" in r.text
    assert 'href="/admin/leads"' in r.text  # ссылка в шапке


def test_lead_sends_telegram(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:ABC")
    monkeypatch.setattr(settings, "telegram_owner_chat_id", "42")
    sent = []
    monkeypatch.setattr(leads, "send_message", lambda chat, text: sent.append((chat, text)))
    uid = _upload(client)
    r = client.post(
        f"/api/v1/uploads/{uid}/request",
        json={
            "material": "RESIN-TOUGH",
            "name": "Петя <b>",
            "phone": "+7 999 000-00-00",
            "comment": "серый",
        },
    )
    assert r.json()["telegram"] is True
    with session_factory()() as s:
        assert s.scalars(select(Lead)).one().telegram_sent is True
    chat, text = sent[0]
    assert chat == "42"
    assert "Смола прочная" in text and "Петя &lt;b&gt;" in text and "серый" in text
    assert f"/api/v1/uploads/{uid}/file" in text
    assert "20 × 30 × 40 мм" in text and "⚠️" not in text


def test_lead_validation(client):
    uid = _upload(client)
    url = f"/api/v1/uploads/{uid}/request"
    assert (
        client.post(url, json={"material": "GOLD", "name": "A", "phone": "89991234567"}).status_code
        == 422
    )
    assert (
        client.post(url, json={"material": "RESIN", "name": "A", "phone": "12"}).status_code == 422
    )
    assert (
        client.post(url, json={"material": "RESIN", "name": "", "phone": "89991234567"}).status_code
        == 422
    )
    r = client.post(
        "/api/v1/uploads/nope/request",
        json={"material": "RESIN", "name": "A", "phone": "89991234567"},
    )
    assert r.status_code == 404
