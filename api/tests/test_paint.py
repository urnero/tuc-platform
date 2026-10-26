"""Раскраска модели по частям (B31)."""

import asyncio
import io
import struct

import pytest
import trimesh
from conftest import REPO_ROOT, box_stl
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.paint as pa
from app.config import settings
from app.models import Event
from app.paint import (
    MAX_PARTS,
    PaintError,
    build_result_name,
    describe,
    parse_colors,
    split_parts,
    validate_colors,
    write_3mf,
)

PALETTE = [
    {"key": "red", "name": "Красный", "hex": "#D32F2F"},
    {"key": "blue", "name": "Синий", "hex": "#1976D2"},
]
BY_KEY = {c["key"]: c for c in PALETTE}


@pytest.fixture(autouse=True)
def colors_yaml(monkeypatch):
    """Палитра — настоящая из config/colors.yaml в корне репо."""
    monkeypatch.setattr(settings, "colors_path", REPO_ROOT / "config" / "colors.yaml")
    monkeypatch.setattr(settings, "redis_url", "")
    pa.reload_colors()
    yield
    pa.reload_colors()


def three_parts_stl() -> bytes:
    """Коробка 40×30×20, шарик радиусом 5 и маленький цилиндр — три отдельные детали."""
    box = trimesh.creation.box(extents=(40, 30, 20))
    ball = trimesh.creation.icosphere(subdivisions=2, radius=5).apply_translation((60, 0, 0))
    pin = trimesh.creation.cylinder(radius=2, height=3).apply_translation((0, 60, 0))
    return trimesh.util.concatenate([box, ball, pin]).export(file_type="stl")


def _upload(client, data=None, name="box.stl"):
    data = data if data is not None else box_stl(40, 30, 20)
    r = client.post("/api/v1/uploads", files={"file": (name, data, "application/octet-stream")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _events(db) -> list[Event]:
    with Session(db) as s:
        return list(s.scalars(select(Event).order_by(Event.id)))


# --- палитра ----------------------------------------------------------------------------


def test_parse_colors_ok():
    colors = parse_colors({"colors": [{"key": "red", "name": " Красный ", "hex": "#d32f2f"}]})
    assert colors == [{"key": "red", "name": "Красный", "hex": "#D32F2F"}]


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ({}, "нет списка"),
        ({"colors": []}, "нет списка"),
        ({"colors": ["red"]}, "строка вида"),
        ({"colors": [{"key": "Красный", "name": "x", "hex": "#000000"}]}, "латиница"),
        ({"colors": [{"key": "red", "name": "", "hex": "#000000"}]}, "нет названия"),
        ({"colors": [{"key": "red", "name": "x", "hex": "red"}]}, "#RRGGBB"),
        (
            {"colors": [{"key": "red", "name": "x", "hex": "#000000"}] * 2},
            "дважды",
        ),
    ],
)
def test_parse_colors_rejects(raw, fragment):
    with pytest.raises(PaintError, match=fragment):
        parse_colors(raw)


def test_repo_colors_yaml_is_valid(client):
    r = client.get("/api/v1/paint/colors")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_parts"] == MAX_PARTS
    keys = [c["key"] for c in body["colors"]]
    assert len(keys) >= 5 and len(set(keys)) == len(keys)
    assert all(c["hex"].startswith("#") and c["name"] for c in body["colors"])


def test_colors_missing_file_503(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "colors_path", tmp_path / "нет.yaml")
    assert client.get("/api/v1/paint/colors").status_code == 503


# --- детали -----------------------------------------------------------------------------


def test_split_parts_sorted_by_volume():
    mesh = trimesh.load(io.BytesIO(three_parts_stl()), file_type="stl", force="mesh")
    pieces = split_parts(mesh)
    assert len(pieces) == 3
    volumes = [abs(float(p.volume)) for p in pieces]
    assert volumes == sorted(volumes, reverse=True)
    assert volumes[0] == pytest.approx(40 * 30 * 20)


def test_split_parts_merges_tail():
    cubes = [
        trimesh.creation.box(extents=(1, 1, 1)).apply_translation((i * 5, 0, 0))
        for i in range(MAX_PARTS + 5)
    ]
    big = trimesh.creation.box(extents=(30, 30, 30)).apply_translation((0, 100, 0))
    pieces = split_parts(trimesh.util.concatenate([big, *cubes]))
    assert len(pieces) == MAX_PARTS
    assert abs(float(pieces[0].volume)) == pytest.approx(27000)
    # хвост: 7 кубиков (всего 18 деталей, 11 показаны отдельно)
    assert pieces[-1].metadata["merged_count"] == 7
    assert len(pieces[-1].faces) == 7 * 12


def test_split_single_body():
    pieces = split_parts(trimesh.creation.box(extents=(10, 10, 10)))
    assert len(pieces) == 1 and "merged_count" not in pieces[0].metadata


def test_parts_api(client):
    uid = _upload(client, three_parts_stl(), "три.stl")
    r = client.get(f"/api/v1/uploads/{uid}/parts")
    assert r.status_code == 200, r.text
    parts = r.json()
    assert parts["units"] == "mm" and parts["max_parts"] == MAX_PARTS
    names = [p["name"] for p in parts["parts"]]
    assert names == ["Деталь 1", "Деталь 2", "Деталь 3"]
    assert parts["parts"][0]["bbox_mm"] == {"x": 40, "y": 30, "z": 20}
    assert parts["parts"][0]["volume_cm3"] == pytest.approx(24.0)
    # детали лежат в STL подряд: first_face + faces = следующий first_face, сумма = triangles
    offsets = [p["first_face"] for p in parts["parts"]]
    sizes = [p["faces"] for p in parts["parts"]]
    assert offsets == [0, sizes[0], sizes[0] + sizes[1]]
    assert sum(sizes) == parts["triangles"]

    f = client.get(f"/api/v1/uploads/{uid}/parts/file")
    assert f.status_code == 200
    assert struct.unpack("<I", f.content[80:84])[0] == parts["triangles"]
    # второй вызов — из кэша (файл не перезаписывается)
    stamp = pa.parts_path(uid).stat().st_mtime_ns
    assert client.get(f"/api/v1/uploads/{uid}/parts").json() == parts
    assert pa.parts_path(uid).stat().st_mtime_ns == stamp


def test_parts_file_404_before_split(client):
    uid = _upload(client)
    assert client.get(f"/api/v1/uploads/{uid}/parts/file").status_code == 404
    assert client.get("/api/v1/uploads/" + "0" * 32 + "/parts").status_code == 404


def test_parts_reset_on_units_change(client):
    uid = _upload(client)
    parts = client.get(f"/api/v1/uploads/{uid}/parts").json()
    assert parts["parts"][0]["bbox_mm"] == {"x": 40, "y": 30, "z": 20}
    client.patch(f"/api/v1/uploads/{uid}", json={"units": "inch"})
    assert not pa.parts_path(uid).exists()
    parts = client.get(f"/api/v1/uploads/{uid}/parts").json()
    assert parts["units"] == "inch"
    assert parts["parts"][0]["bbox_mm"] == {"x": 1016, "y": 762, "z": 508}


# --- проверка цветов, тексты ------------------------------------------------------------


def test_validate_colors():
    assert validate_colors(["red", "blue"], 2, PALETTE) == (["red", "blue"], {})
    assert validate_colors(["red"], 2, PALETTE)[1] == {
        "colors": "Нужно 2 цветов — по одному на каждую деталь."
    }
    assert "pink" in validate_colors(["red", "pink"], 2, PALETTE)[1]["colors"]
    assert validate_colors(["red", 5], 2, PALETTE)[1]["colors"].startswith("Нет такого")
    assert "список" in validate_colors("red", 1, PALETTE)[1]["colors"]


def test_describe_and_result_name():
    parts = [{"name": "Деталь 1"}, {"name": "Деталь 2"}, {"name": "Мелкие детали (3 шт.)"}]
    assert describe(parts, ["red", "blue", "red"], BY_KEY) == (
        "Деталь 1 — красный, Деталь 2 — синий, Мелкие детали (3 шт.) — красный"
    )
    assert describe(parts[:2], ["red", "red"], BY_KEY) == "вся модель — красный"
    assert build_result_name("Кронштейн.stl", ["red", "blue"], BY_KEY) == "Кронштейн — 2 цвета.3mf"
    assert build_result_name("box.3mf", ["red", "red"], BY_KEY) == "box — красный.3mf"
    five = PALETTE + [{"key": k, "name": k, "hex": "#000000"} for k in ("a", "b", "c")]
    by = {c["key"]: c for c in five}
    assert build_result_name("x.stl", ["red", "blue", "a", "b", "c"], by) == "x — 5 цветов.3mf"


# --- 3MF --------------------------------------------------------------------------------


def test_write_3mf_roundtrip():
    box = trimesh.creation.box(extents=(10, 20, 30))
    ball = trimesh.creation.icosphere(radius=4).apply_translation((30, 0, 0))
    red, blue = BY_KEY["red"], BY_KEY["blue"]
    data = write_3mf(
        [
            {"name": "Корпус «A» & B", "vertices": box.vertices, "faces": box.faces, "color": red},
            {"name": "Шар", "vertices": ball.vertices, "faces": ball.faces, "color": blue},
            {"name": "Ещё", "vertices": box.vertices, "faces": box.faces, "color": red},
        ],
        title="тест",
    )
    scene = trimesh.load(io.BytesIO(data), file_type="3mf")
    assert isinstance(scene, trimesh.Scene)
    assert set(scene.geometry) == {"Корпус «A» & B", "Шар", "Ещё"}
    assert len(scene.geometry["Шар"].faces) == len(ball.faces)
    assert scene.geometry["Корпус «A» & B"].volume == pytest.approx(6000)

    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert set(zf.namelist()) == {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"}
        xml = zf.read("3D/3dmodel.model").decode("utf-8")
    # два цвета — два материала; объекты ссылаются на них по индексу
    assert xml.count("<base ") == 2
    assert '<base name="Красный" displaycolor="#D32F2FFF"/>' in xml
    assert '<object id="2" name="Корпус «A» &amp; B" type="model" pid="1" pindex="0">' in xml
    assert 'id="3" name="Шар" type="model" pid="1" pindex="1"' in xml
    assert 'id="4" name="Ещё" type="model" pid="1" pindex="0"' in xml
    assert xml.count("<item ") == 3
    assert '<metadata name="Title">тест</metadata>' in xml


# --- сборка через API -------------------------------------------------------------------


def test_paint_makes_new_upload(client, db):
    uid = _upload(client, three_parts_stl(), "три детали.stl")
    r = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["red", "blue", "red"]})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "done", job
    assert job["error"] is None and job["colors"] == ["red", "blue", "red"]
    new_id = job["result_upload_id"]
    assert new_id and new_id != uid

    meta = client.get(f"/api/v1/uploads/{new_id}").json()
    assert meta["source"] == "paint" and meta["ext"] == "3mf" and meta["units"] == "mm"
    assert meta["original_name"] == "три детали — 2 цвета.3mf"
    paint = meta["paint"]
    assert paint["parent_id"] == uid and paint["parent_name"] == "три детали.stl"
    assert paint["job_id"] == job["id"]
    assert paint["summary"] == "Деталь 1 — красный, Деталь 2 — синий, Деталь 3 — красный"
    assert [c["key"] for c in paint["colors"]] == ["red", "blue"]
    assert paint["parts"][1] == {
        "name": "Деталь 2",
        "color": "blue",
        "color_name": "Синий",
        "hex": "#1976D2",
    }
    # геометрия та же: объём всех трёх деталей
    assert meta["mesh"]["volume_cm3"] == pytest.approx(
        client.get(f"/api/v1/uploads/{uid}").json()["mesh"]["volume_cm3"], rel=0.01
    )
    assert meta["mesh"]["watertight"] is True

    # сам файл — 3MF с тремя объектами и двумя материалами
    file = client.get(f"/api/v1/uploads/{new_id}/file")
    assert file.status_code == 200
    scene = trimesh.load(io.BytesIO(file.content), file_type="3mf")
    assert set(scene.geometry) == {"Деталь 1", "Деталь 2", "Деталь 3"}

    # статус по id; события: paint_build и upload новой загрузки с source = paint
    assert client.get(f"/api/v1/uploads/{uid}/paints/{job['id']}").json()["status"] == "done"
    builds = [e for e in _events(db) if e.name == "paint_build"]
    assert builds and builds[0].upload_id == uid and builds[0].props["colors"] == 2
    uploads = [e for e in _events(db) if e.name == "upload" and e.upload_id == new_id]
    assert uploads and uploads[0].props["source"] == "paint"
    assert uploads[0].props["parent_upload_id"] == uid

    # раскрашенную модель можно рассчитать: цена видит «decor»
    from app.quotes import decor_summary

    assert decor_summary(meta) == paint["summary"]
    assert decor_summary({"emboss": {"summary": "Надпись"}}) == "Надпись"
    assert decor_summary({}) is None


def test_paint_single_color_name_and_cache(client):
    uid = _upload(client)
    r = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["green"]})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "done", job
    meta = client.get(f"/api/v1/uploads/{job['result_upload_id']}").json()
    assert meta["original_name"] == "box — зелёный.3mf"
    assert meta["paint"]["summary"] == "вся модель — зелёный"
    # те же цвета → та же сборка; другие → новая
    again = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["green"]}).json()
    assert again["id"] == job["id"] and again["result_upload_id"] == job["result_upload_id"]
    other = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["red"]}).json()
    assert other["id"] != job["id"]


def test_paint_validation_and_404(client):
    uid = _upload(client, three_parts_stl())
    r = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["red"]})
    assert r.status_code == 422
    assert r.json()["detail"]["errors"]["colors"] == "Нужно 3 цветов — по одному на каждую деталь."
    r = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["red", "blue", "pink"]})
    assert r.status_code == 422 and "pink" in r.json()["detail"]["errors"]["colors"]
    assert client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": "red"}).status_code == 422
    assert client.post("/api/v1/uploads/" + "0" * 32 + "/paints", json={}).status_code == 404
    assert client.get(f"/api/v1/uploads/{uid}/paints/{'0' * 32}").status_code == 404
    assert client.get(f"/api/v1/uploads/{uid}/paints/bad").status_code == 404


def test_paint_inherits_material_from_editor_upload(client):
    uid = _upload(client)
    meta_path = settings.data_dir / "uploads" / uid / "meta.json"
    import json

    meta = json.loads(meta_path.read_text("utf-8"))
    meta["source"] = "editor"
    meta["editor"] = {"slug": "spacer", "title": "Проставка", "material": "PETG"}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    job = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["blue"]}).json()
    assert job["status"] == "done", job
    meta = client.get(f"/api/v1/uploads/{job['result_upload_id']}").json()
    assert meta["paint"]["material"] == "PETG"


def test_paint_queued_with_redis(client, monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    calls = []

    async def fake_enqueue(request, upload_id, job_id, attempt=0):
        calls.append((upload_id, job_id))

    monkeypatch.setattr(pa, "_enqueue", fake_enqueue)
    uid = _upload(client)
    r = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["red"]})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert calls == [(uid, r.json()["id"])]
    again = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["red"]}).json()
    assert again["status"] == "queued"
    assert len(calls) == 1

    from app.worker import WorkerSettings, paint_upload

    assert paint_upload in WorkerSettings.functions
    result = asyncio.run(paint_upload({}, uid, r.json()["id"]))
    assert result["status"] == "done", result
    assert client.get(f"/api/v1/uploads/{result['result_upload_id']}").json()["source"] == "paint"


def test_paint_error_is_recorded(client, monkeypatch):
    uid = _upload(client)

    def boom(*a, **k):
        raise PaintError("сломалось")

    monkeypatch.setattr(pa, "write_3mf", boom)
    job = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["red"]}).json()
    assert job["status"] == "error" and job["error"] == "сломалось"
    assert job["result_upload_id"] is None
    # повтор после ошибки — новая попытка
    monkeypatch.setattr(pa, "write_3mf", write_3mf)
    again = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": ["red"]}).json()
    assert again["status"] == "done" and again["attempt"] == 1


def test_painted_upload_can_be_painted_again_and_sliced(client, fake_slicer):
    """Результат — обычная загрузка: разбирается на детали и считается слайсером."""
    uid = _upload(client, three_parts_stl())
    colors = ["red", "blue", "red"]
    job = client.post(f"/api/v1/uploads/{uid}/paints", json={"colors": colors}).json()
    new_id = job["result_upload_id"]
    parts = client.get(f"/api/v1/uploads/{new_id}/parts").json()
    assert len(parts["parts"]) == 3
    r = client.post(f"/api/v1/uploads/{new_id}/slice", json={"material": "PLA"})
    assert r.status_code in (200, 202), r.text
    assert r.json()["status"] == "done", r.json()
