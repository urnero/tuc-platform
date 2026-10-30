"""Каталог моделей (B20): чтение catalog.yaml, карточки, превью PNG, «Заказать» → загрузка."""

import pytest
import trimesh
from conftest import REPO_ROOT, box_stl

from app import catalog as cat
from app.catalog import CatalogError, parse_catalog
from app.config import settings
from app.render import render_png

YAML_OK = """
categories:
  - slug: home
    title: Для дома
    text: Мелочи.
  - slug: empty
    title: Пустая
models:
  - slug: cube
    title: Кубик
    category: home
    text: Простой куб.
    file: cube.stl
    material: petg
    license: Своя модель
  - slug: no-file
    title: Без файла
    category: home
    file: missing.stl
"""


@pytest.fixture
def catalog_dir(tmp_path, monkeypatch, data_dir):
    """Временный каталог: catalog.yaml из YAML_OK и один настоящий STL (куб 20×30×40)."""
    folder = tmp_path / "catalog"
    (folder / "models").mkdir(parents=True)
    (folder / "catalog.yaml").write_text(YAML_OK, "utf-8")
    (folder / "models" / "cube.stl").write_bytes(box_stl())
    monkeypatch.setattr(settings, "catalog_dir", folder)
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    cat.reload_catalog()
    yield folder
    cat.reload_catalog()


# --- parse_catalog ---------------------------------------------------------------------


def test_parse_ok():
    import yaml

    catalog = parse_catalog(yaml.safe_load(YAML_OK))
    assert [c.slug for c in catalog.categories] == ["home", "empty"]
    cube = catalog.get("cube")
    assert cube is not None
    assert cube.material == "PETG"  # приводим к верхнему регистру, как в pricing.yaml
    assert cube.ext == "stl"
    assert catalog.get("nope") is None


CAT_A = [{"slug": "a", "title": "x"}]


def model_row(**extra) -> dict:
    return {"slug": "m", "title": "x", "category": "a", "file": "m.stl", **extra}


@pytest.mark.parametrize(
    "raw, text",
    [
        ({"categories": [{"slug": "Дом", "title": "x"}]}, "только a-z"),
        ({"categories": CAT_A + [{"slug": "a", "title": "y"}]}, "дважды"),
        ({"categories": [], "models": [model_row()]}, "неизвестная категория"),
        ({"categories": CAT_A, "models": [model_row(file="m.obj")]}, "stl или 3mf"),
        ({"categories": CAT_A, "models": [model_row(title="")]}, "«title»"),
        ([], "ожидались разделы"),
    ],
)
def test_parse_errors(raw, text):
    with pytest.raises(CatalogError, match=text):
        parse_catalog(raw)


def test_file_name_without_paths():
    """«../../etc/passwd» в file — берём только имя файла."""
    raw = {
        "categories": [{"slug": "a", "title": "x"}],
        "models": [{"slug": "m", "title": "x", "category": "a", "file": "../../secret.stl"}],
    }
    assert parse_catalog(raw).models[0].file == "secret.stl"


def test_repo_catalog_is_valid():
    """Настоящий catalog/catalog.yaml в репо: разбирается, все файлы на месте, сетки читаются."""
    import yaml

    root = REPO_ROOT / "catalog"
    catalog = parse_catalog(yaml.safe_load((root / "catalog.yaml").read_text("utf-8")))
    assert catalog.models, "каталог пустой"
    for model in catalog.models:
        path = root / "models" / model.file
        assert path.is_file(), f"нет файла {path}"
        mesh = trimesh.load(path, force="mesh")
        assert len(mesh.faces) > 0
        assert mesh.extents.max() <= 250, f"{model.slug} не влезает в принтер"


# --- API ---------------------------------------------------------------------------------


def test_get_catalog(client, catalog_dir):
    r = client.get("/api/v1/catalog")
    assert r.status_code == 200, r.text
    data = r.json()
    assert [c["slug"] for c in data["categories"]] == ["home", "empty"]
    assert data["categories"][0]["count"] == 2
    assert data["categories"][1]["count"] == 0
    cube = next(m for m in data["models"] if m["slug"] == "cube")
    assert cube["preview_url"] == "/api/v1/catalog/cube/preview.png"
    assert cube["mesh"]["bbox_mm"] == {"x": 20.0, "y": 30.0, "z": 40.0}
    assert cube["material"] == "PETG"
    # модель без файла — в списке, но без габаритов; каталог целиком не ломается
    missing = next(m for m in data["models"] if m["slug"] == "no-file")
    assert missing["mesh"] is None


def test_get_model_and_404(client, catalog_dir):
    assert client.get("/api/v1/catalog/cube").json()["title"] == "Кубик"
    assert client.get("/api/v1/catalog/nope").status_code == 404
    assert client.get("/api/v1/catalog/..").status_code == 404
    assert client.get("/api/v1/catalog/no-file/file").status_code == 404
    assert client.get("/api/v1/catalog/no-file/preview.png").status_code == 404


def test_model_file(client, catalog_dir):
    r = client.get("/api/v1/catalog/cube/file")
    assert r.status_code == 200
    assert r.content == box_stl()


def test_preview_png_cached(client, catalog_dir):
    r = client.get("/api/v1/catalog/cube/preview.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    cached = list((settings.data_dir / "catalog" / "previews").glob("cube-*.png"))
    assert len(cached) == 1
    # второй запрос — из кэша, байт в байт
    assert client.get("/api/v1/catalog/cube/preview.png").content == r.content


def test_broken_yaml_is_500_with_text(client, catalog_dir):
    (catalog_dir / "catalog.yaml").write_text("models:\n  - slug: x\n", "utf-8")
    cat.reload_catalog()
    r = client.get("/api/v1/catalog")
    assert r.status_code == 500
    assert "catalog.yaml" in r.json()["detail"]


def test_catalog_reloads_when_file_changes(client, catalog_dir):
    assert len(client.get("/api/v1/catalog").json()["models"]) == 2
    (catalog_dir / "catalog.yaml").write_text(
        "categories:\n  - slug: a\n    title: A\nmodels: []\n", "utf-8"
    )
    import os
    import time

    # дата файла — ключ кэша; на быстрых ФС правим её руками, чтобы не ждать
    future = time.time() + 5
    os.utime(catalog_dir / "catalog.yaml", (future, future))
    assert client.get("/api/v1/catalog").json()["models"] == []


def test_order_from_catalog_makes_upload(client, catalog_dir):
    """Кнопка «Заказать»: копия модели становится обычной загрузкой со всеми полями."""
    r = client.post("/api/v1/catalog/cube/upload")
    assert r.status_code == 201, r.text
    meta = r.json()
    upload_id = meta["id"]
    assert meta["source"] == "catalog"
    assert meta["catalog"] == {"slug": "cube", "title": "Кубик", "material": "PETG"}
    assert meta["original_name"] == "Кубик.stl"
    assert meta["mesh"]["bbox_mm"] == {"x": 20.0, "y": 30.0, "z": 40.0}
    # дальше работает весь обычный путь загрузки
    assert client.get(f"/api/v1/uploads/{upload_id}").json()["id"] == upload_id
    assert client.get(f"/api/v1/uploads/{upload_id}/file").content == box_stl()
    # событие воронки записано с источником
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db import get_engine
    from app.models import Event

    with Session(get_engine()) as db:
        event = db.execute(select(Event).where(Event.upload_id == upload_id)).scalar_one()
    assert event.name == "upload"
    assert event.props["source"] == "catalog"
    assert event.props["catalog_slug"] == "cube"


def test_order_from_catalog_missing_file(client, catalog_dir):
    assert client.post("/api/v1/catalog/no-file/upload").status_code == 404
    assert client.post("/api/v1/catalog/nope/upload").status_code == 404


# --- render ------------------------------------------------------------------------------


def test_render_png_draws_something():
    png = render_png(trimesh.creation.box(extents=(20, 30, 40)), size=64)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(png))
    assert img.size == (64, 64)
    alpha = img.getchannel("A")
    opaque = sum(1 for a in alpha.getdata() if a > 0)
    assert 0.2 * 64 * 64 < opaque < 0.95 * 64 * 64  # модель есть и не на весь кадр
    # середина — цвет модели (бирюзовый), угол — прозрачный
    r, g, b, a = img.getpixel((32, 32))
    assert a == 255 and g > r
    assert img.getpixel((1, 1))[3] == 0


def test_render_empty_mesh():
    png = render_png(trimesh.Trimesh(), size=32)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


# --- ориентир цены в карточке (UX «цена до загрузки») ----------------------------------

def test_card_has_price_hint(client, catalog_dir):
    data = client.get("/api/v1/catalog").json()
    cube = next(m for m in data["models"] if m["slug"] == "cube")
    # куб 20×30×40 в PETG — маленький, одна штука упирается в минимальный заказ
    from app.pricing import load_pricing

    min_order = round(load_pricing().min_order)
    assert cube["price"] == {"total": min_order, "material": "PETG", "min_order": True}
    missing = next(m for m in data["models"] if m["slug"] == "no-file")
    assert missing["price"] is None


def test_price_hint_falls_back_to_pla_and_survives_bad_pricing(monkeypatch):
    monkeypatch.setattr(settings, "pricing_path", REPO_ROOT / "config" / "pricing.yaml")
    from app.meshcheck import MeshInfo
    from app.pricing import PricingError

    info = MeshInfo(12, 8, {"x": 100, "y": 100, "z": 100}, 1000.0, 600.0, True, False, "mm")
    model = cat.Model("big", "Куб", "home", "", "big.stl", "RESIN", "")
    hint = cat.price_hint(model, info)
    assert hint["material"] == "PLA" and hint["min_order"] is False and hint["total"] > 0

    def broken():
        raise PricingError("битый прайс")

    monkeypatch.setattr(cat, "load_pricing", broken)
    assert cat.price_hint(model, info) is None
