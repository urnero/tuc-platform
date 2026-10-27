"""Тиснение надписи / логотипа на загруженной модели (B30)."""

import asyncio
import math
import shutil

import numpy as np
import pytest
import trimesh
from conftest import box_stl
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.emboss as em
from app.config import settings
from app.emboss import (
    DEFAULTS,
    EmbossError,
    check_svg,
    describe,
    face_transform,
    merge,
    validate_params,
)
from app.models import Event

SVG_OK = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">'
    b'<circle cx="30" cy="30" r="25"/><rect x="60" y="10" width="35" height="40"/></svg>'
)


def _upload(client, data=None, name="box.stl"):
    data = data if data is not None else box_stl(40, 30, 20)
    r = client.post("/api/v1/uploads", files={"file": (name, data, "application/octet-stream")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _emboss(client, upload_id, **params):
    body = {"kind": "text", "text": "ТУЦ", "size_mm": 8, "depth_mm": 1, "face": "top"} | params
    return client.post(f"/api/v1/uploads/{upload_id}/embosses", json={"params": body})


def _events(db) -> list[Event]:
    with Session(db) as s:
        return list(s.scalars(select(Event).order_by(Event.id)))


# --- SVG --------------------------------------------------------------------------------


def test_check_svg_ok():
    assert check_svg(SVG_OK) is None


@pytest.mark.parametrize(
    "data, fragment",
    [
        (b"not xml at all <", "прочитать"),
        (b"<html><body/></html>", "Нужен файл SVG"),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><rect/></svg>',
            "скрипт",
        ),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            b'<image xlink:href="http://x/y.png"/><rect/></svg>',
            "скрипт",
        ),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><a href="/x"><rect/></a></svg>', "скрипт"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><text>TUC</text><rect/></svg>', "кривые"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>', "нет контуров"),
        (b"<svg>" + b"<!-- x -->" * 200_000 + b"<rect/></svg>", "больше 1 МБ"),
    ],
)
def test_check_svg_rejects(data, fragment):
    error = check_svg(data)
    assert error and fragment in error


def test_logo_upload_and_delete(client):
    uid = _upload(client)
    r = client.post(
        f"/api/v1/uploads/{uid}/logo", files={"file": ("Лого.svg", SVG_OK, "image/svg+xml")}
    )
    assert r.status_code == 200, r.text
    assert r.json()["logo"] == {"name": "Лого.svg", "size_bytes": len(SVG_OK)}
    assert (settings.data_dir / "uploads" / uid / "logo.svg").read_bytes() == SVG_OK
    # в meta.json тоже
    assert client.get(f"/api/v1/uploads/{uid}").json()["logo"]["name"] == "Лого.svg"

    r = client.delete(f"/api/v1/uploads/{uid}/logo")
    assert r.status_code == 200
    assert "logo" not in r.json()
    assert not (settings.data_dir / "uploads" / uid / "logo.svg").exists()


def test_logo_upload_rejects(client):
    uid = _upload(client)
    r = client.post(f"/api/v1/uploads/{uid}/logo", files={"file": ("x.svg", b"<svg/>", "x")})
    assert r.status_code == 422
    assert "контуров" in r.json()["detail"]
    big = b"<svg>" + b" " * (1024 * 1024 + 1) + b"</svg>"
    r = client.post(f"/api/v1/uploads/{uid}/logo", files={"file": ("x.svg", big, "x")})
    assert r.status_code == 413
    assert (
        client.post(
            "/api/v1/uploads/" + "0" * 32 + "/logo", files={"file": ("x", b"x")}
        ).status_code
        == 404
    )


# --- параметры --------------------------------------------------------------------------


def test_validate_defaults_and_cleaning():
    clean, errors = validate_params(
        {"text": "  ТУЦ \n 42  ", "size_mm": "12,5", "bold": "false"}, False
    )
    assert errors == {}
    assert clean == {**DEFAULTS, "text": "ТУЦ 42", "size_mm": 12.5, "bold": False}


def test_validate_errors():
    _, errors = validate_params(
        {
            "kind": "logo",
            "text": "x" * 41,
            "font": "comic",
            "style": "flat",
            "face": "inside",
            "size_mm": 0,
            "depth_mm": 99,
            "dx": "много",
            "angle": 400,
            "bold": "maybe",
            "foo": 1,
        },
        has_logo=False,
    )
    assert errors == {
        "kind": "Сначала загрузите логотип (SVG).",
        "text": "Не длиннее 40 символов.",
        "font": "Выберите один из вариантов.",
        "style": "Выберите один из вариантов.",
        "face": "Выберите один из вариантов.",
        "size_mm": "Не меньше 3 мм.",
        "depth_mm": "Не больше 10 мм.",
        "dx": "Нужно число.",
        "angle": "Не больше 180 °.",
        "bold": "Нужно да или нет.",
        "foo": "Неизвестный параметр.",
    }
    assert validate_params({"text": ""}, False)[1] == {"text": "Введите надпись."}
    assert validate_params({"text": None}, False)[1] == {"text": "Нужен текст."}
    assert validate_params([], False)[1] == {"params": "Ожидался словарь параметров."}
    # логотип есть — текст не обязателен и в параметры не попадает
    clean, errors = validate_params({"kind": "logo", "text": "лишнее"}, has_logo=True)
    assert errors == {} and clean["text"] == ""


def test_describe():
    clean, _ = validate_params(
        {"text": "ТУЦ", "size_mm": 8, "depth_mm": 1.5, "face": "front"}, False
    )
    assert describe(clean) == "Надпись «ТУЦ» (без засечек, жирный) 8 мм, выпуклая 1,5 мм, спереди"
    clean, _ = validate_params(
        {"kind": "logo", "style": "engraved", "size_mm": 20, "dx": 5, "angle": -15, "bold": False},
        True,
    )
    assert describe(clean, "logo.svg") == (
        "Логотип logo.svg шириной 20 мм, углублённый 1 мм, спереди, сдвиг 5 / 0 мм, поворот -15°"
    )


# --- геометрия --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "face, center, normal, right, up",
    [
        ("top", (5, 10, 30), (0, 0, 1), (1, 0, 0), (0, 1, 0)),
        ("bottom", (5, 10, 0), (0, 0, -1), (1, 0, 0), (0, -1, 0)),
        ("front", (5, 0, 15), (0, -1, 0), (1, 0, 0), (0, 0, 1)),
        ("back", (5, 20, 15), (0, 1, 0), (-1, 0, 0), (0, 0, 1)),
        ("right", (10, 10, 15), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ("left", (0, 10, 15), (-1, 0, 0), (0, -1, 0), (0, 0, 1)),
    ],
)
def test_face_transform(face, center, normal, right, up):
    """Центр фигуры — в центре грани, «лицо» — наружу, dx — вправо и dy — вверх для зрителя."""
    bounds = np.array([[0.0, 0.0, 0.0], [10.0, 20.0, 30.0]])
    m = face_transform(bounds, face, 0, 0)
    assert np.allclose(m @ [0, 0, 0, 1], [*center, 1], atol=1e-9)
    assert np.allclose(m @ [0, 0, 1, 0], [*normal, 0], atol=1e-9)
    assert np.allclose(m @ [1, 0, 0, 0], [*right, 0], atol=1e-9)
    assert np.allclose(m @ [0, 1, 0, 0], [*up, 0], atol=1e-9)
    shifted = face_transform(bounds, face, 3, 2) @ [0, 0, 0, 1]
    expected = np.array(center) + 3 * np.array(right) + 2 * np.array(up)
    assert np.allclose(shifted[:3], expected, atol=1e-9)


def _dec(h=2.0):
    """Тиснение «как из OpenSCAD»: столбик 4×4 мм от z = -0.3 до z = h."""
    d = trimesh.creation.box(extents=(4, 4, h + 0.3))
    d.apply_translation((0, 0, (h - 0.3) / 2))
    return d


def test_merge_raised_and_engraved():
    box = trimesh.creation.box(extents=(20, 20, 10))
    dec = _dec()
    dec.apply_transform(face_transform(box.bounds, "top", 0, 0))
    raised, warnings = merge(box, dec.copy(), "raised")
    assert warnings == [] and raised.is_watertight
    assert math.isclose(raised.volume, box.volume + 4 * 4 * 2, rel_tol=1e-6)
    assert math.isclose(raised.bounds[1][2], 5 + 2, abs_tol=1e-6)

    cutter = _dec(2.0)
    cutter.apply_translation((0, 0, -1.7))  # как в scad: от -depth до +overlap
    cutter.apply_transform(face_transform(box.bounds, "top", 0, 0))
    engraved, warnings = merge(box, cutter, "engraved")
    assert warnings == [] and engraved.is_watertight
    assert math.isclose(engraved.volume, box.volume - 4 * 4 * 2, rel_tol=1e-6)
    assert math.isclose(engraved.bounds[1][2], 5, abs_tol=1e-6)


def test_merge_open_mesh():
    """Незамкнутую модель выпуклая надпись не ломает (кладём рядом), углублённая — ошибка."""
    plane = trimesh.Trimesh(
        vertices=[[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], faces=[[0, 1, 2], [0, 2, 3]]
    )
    dec = _dec()
    result, warnings = merge(plane, dec.copy(), "raised")
    assert warnings == ["merged_without_boolean"]
    assert len(result.faces) == len(plane.faces) + len(dec.faces)
    with pytest.raises(EmbossError, match="не замкнута"):
        merge(plane, dec, "engraved")


# --- API --------------------------------------------------------------------------------


def test_emboss_makes_new_upload(client, fake_openscad, db):
    uid = _upload(client)
    r = _emboss(client, uid, face="front", dx=3)
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "done", job
    assert job["error"] is None and job["warnings"] == []
    assert job["upload_id"] == uid
    new_id = job["result_upload_id"]
    assert new_id and new_id != uid

    # Подделка OpenSCAD пишет куб 10 мм вокруг нуля; наша матрица ставит его на грань спереди,
    # половина (5 мм) торчит наружу по -Y.
    meta = client.get(f"/api/v1/uploads/{new_id}").json()
    assert meta["source"] == "emboss"
    assert meta["ext"] == "stl" and meta["units"] == "mm"
    assert meta["original_name"] == "box + «ТУЦ».stl"
    assert meta["emboss"]["parent_id"] == uid
    assert meta["emboss"]["parent_name"] == "box.stl"
    assert meta["emboss"]["job_id"] == job["id"]
    assert meta["emboss"]["summary"] == (
        "Надпись «ТУЦ» (без засечек, жирный) 8 мм, выпуклая 1 мм, спереди, сдвиг 3 / 0 мм"
    )
    assert meta["mesh"]["bbox_mm"] == {"x": 40, "y": 35, "z": 20}
    assert meta["mesh"]["watertight"] is True
    # файл результата открывается как модель
    file = client.get(f"/api/v1/uploads/{new_id}/file")
    assert file.status_code == 200 and len(file.content) > 84
    # исходная загрузка не изменилась
    assert client.get(f"/api/v1/uploads/{uid}").json()["mesh"]["bbox_mm"] == {
        "x": 40,
        "y": 30,
        "z": 20,
    }

    # В OpenSCAD ушли именно параметры тиснения, текст — в кавычках.
    dec_params = em.decoration_path(uid, job["id"]).with_name(f"{job['id']}.stl.params.json")
    import json

    sent = json.loads(dec_params.read_text("utf-8"))
    assert sent["text"] == '"ТУЦ"' and sent["kind"] == '"text"' and sent["style"] == '"raised"'
    assert sent["logo_file"] == '""' and sent["size_mm"] == "8.0"

    # статус по id
    assert client.get(f"/api/v1/uploads/{uid}/embosses/{job['id']}").json()["status"] == "done"
    # события: emboss_build и upload новой загрузки с source = emboss
    names = [(e.name, e.upload_id) for e in _events(db)]
    assert (uid, "emboss_build") in [(u, n) for n, u in names]
    uploads = [e for e in _events(db) if e.name == "upload" and e.upload_id == new_id]
    assert uploads and uploads[0].props["source"] == "emboss"
    assert uploads[0].props["parent_upload_id"] == uid


def test_emboss_cached(client, fake_openscad, db):
    uid = _upload(client)
    first = _emboss(client, uid).json()
    second = _emboss(client, uid).json()
    assert second["id"] == first["id"]
    assert second["result_upload_id"] == first["result_upload_id"]
    # второй раз OpenSCAD не запускали, а событие с cached = true записано
    builds = [e for e in _events(db) if e.name == "emboss_build"]
    assert [e.props["cached"] for e in builds] == [False, True]
    # другие параметры — другая сборка
    assert _emboss(client, uid, depth_mm=2).json()["id"] != first["id"]


def test_emboss_engraved_cuts(client, fake_openscad):
    uid = _upload(client)
    before = client.get(f"/api/v1/uploads/{uid}").json()["mesh"]["volume_cm3"]
    job = _emboss(client, uid, style="engraved").json()
    assert job["status"] == "done", job
    after = client.get(f"/api/v1/uploads/{job['result_upload_id']}").json()["mesh"]
    assert after["volume_cm3"] < before
    assert after["bbox_mm"] == {"x": 40, "y": 30, "z": 20}  # ничего не торчит


def test_emboss_logo_needs_file(client, fake_openscad):
    uid = _upload(client)
    r = _emboss(client, uid, kind="logo")
    assert r.status_code == 422
    assert r.json()["detail"]["errors"] == {"kind": "Сначала загрузите логотип (SVG)."}
    client.post(
        f"/api/v1/uploads/{uid}/logo", files={"file": ("logo.svg", SVG_OK, "image/svg+xml")}
    )
    job = _emboss(client, uid, kind="logo", size_mm=20).json()
    assert job["status"] == "done", job
    meta = client.get(f"/api/v1/uploads/{job['result_upload_id']}").json()
    assert meta["original_name"] == "box + логотип.stl"
    assert meta["emboss"]["summary"].startswith("Логотип logo.svg шириной 20 мм")


def test_emboss_validation_and_404(client, fake_openscad):
    uid = _upload(client)
    r = _emboss(client, uid, text="", face="up")
    assert r.status_code == 422
    assert r.json()["detail"]["errors"] == {
        "text": "Введите надпись.",
        "face": "Выберите один из вариантов.",
    }
    assert client.post("/api/v1/uploads/" + "0" * 32 + "/embosses", json={}).status_code == 404
    assert client.get(f"/api/v1/uploads/{uid}/embosses/" + "0" * 32).status_code == 404
    assert client.get(f"/api/v1/uploads/{uid}/embosses/nope").status_code == 404


def test_emboss_openscad_error(client, fake_openscad, monkeypatch):
    uid = _upload(client)
    monkeypatch.setattr(settings, "openscad_bin", "/nonexistent/openscad")
    job = _emboss(client, uid).json()
    assert job["status"] == "error"
    assert "OpenSCAD" in job["error"]
    assert job["result_upload_id"] is None


def test_emboss_inherits_material_from_editor_upload(client, fake_openscad):
    uid = _upload(client)
    # как будто загрузка пришла из каталога (B20)
    meta = client.get(f"/api/v1/uploads/{uid}").json()
    meta["source"] = "catalog"
    meta["catalog"] = {"slug": "x", "title": "X", "material": "PETG"}
    em._save_meta(em.upload_dir(uid), meta)
    job = _emboss(client, uid).json()
    result = client.get(f"/api/v1/uploads/{job['result_upload_id']}").json()
    assert result["emboss"]["material"] == "PETG"


def test_emboss_queued_with_redis(client, fake_openscad, monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    calls = []

    async def fake_enqueue(request, upload_id, job_id, attempt=0):
        calls.append((upload_id, job_id))

    monkeypatch.setattr(em, "_enqueue", fake_enqueue)
    uid = _upload(client)
    r = _emboss(client, uid)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert calls == [(uid, r.json()["id"])]
    assert _emboss(client, uid).json()["status"] == "queued"
    assert len(calls) == 1

    from app.worker import WorkerSettings, emboss_upload

    assert emboss_upload in WorkerSettings.functions
    result = asyncio.run(emboss_upload({}, uid, r.json()["id"]))
    assert result["status"] == "done", result
    assert client.get(f"/api/v1/uploads/{result['result_upload_id']}").json()["source"] == "emboss"


def test_options(client):
    r = client.get("/api/v1/emboss/options")
    assert r.status_code == 200
    body = r.json()
    assert body["defaults"] == DEFAULTS
    assert [f["value"] for f in body["faces"]] == list(em.FACES)
    assert body["text_maxlen"] == 40 and body["size_mm"]["min"] == 3


# --- настоящий OpenSCAD -----------------------------------------------------------------


@pytest.mark.skipif(shutil.which("openscad") is None, reason="нужен настоящий OpenSCAD")
def test_emboss_with_real_openscad(client, monkeypatch):
    monkeypatch.setattr(settings, "openscad_bin", "openscad")
    monkeypatch.setattr(settings, "redis_url", "")
    uid = _upload(client, box_stl(60, 40, 30))
    before = client.get(f"/api/v1/uploads/{uid}").json()["mesh"]

    job = _emboss(client, uid, text="ТУЦ 42", face="front", size_mm=10, depth_mm=1.5).json()
    assert job["status"] == "done", job
    after = client.get(f"/api/v1/uploads/{job['result_upload_id']}").json()["mesh"]
    assert after["watertight"] is True
    assert after["volume_cm3"] > before["volume_cm3"]
    # надпись торчит спереди (по -Y) ровно на 1,5 мм, по X и Z габариты те же
    assert after["bbox_mm"] == {"x": 60, "y": 41.5, "z": 30}

    client.post(
        f"/api/v1/uploads/{uid}/logo", files={"file": ("logo.svg", SVG_OK, "image/svg+xml")}
    )
    job = _emboss(
        client, uid, kind="logo", style="engraved", face="top", size_mm=30, angle=20
    ).json()
    assert job["status"] == "done", job
    after = client.get(f"/api/v1/uploads/{job['result_upload_id']}").json()["mesh"]
    assert after["watertight"] is True
    assert after["volume_cm3"] < before["volume_cm3"]
    assert after["bbox_mm"] == before["bbox_mm"]
