"""Каталог готовых моделей (B20).

Источник — папка CATALOG_DIR (по умолчанию `catalog/` в корне репо):
    catalog.yaml      — категории и модели (правит владелец, формат описан в самом файле)
    models/<file>     — STL/3MF моделей

GET  /api/v1/catalog                     — категории и карточки: название, описание, габариты,
                                           объём, материал по умолчанию, адрес превью.
GET  /api/v1/catalog/{slug}              — одна модель.
GET  /api/v1/catalog/{slug}/preview.png  — превью (рисуем сами, app/render.py; кэш в
                                           DATA_DIR/catalog/previews/).
GET  /api/v1/catalog/{slug}/file         — файл модели для 3D-просмотра в браузере.
POST /api/v1/catalog/{slug}/upload       — «Заказать»: копируем модель в загрузки
                                           (DATA_DIR/uploads/<id>/, как у клиентской загрузки)
                                           и отдаём её meta. Дальше всё как обычно:
                                           /upload/<id> → расчёт печати → цена → заказ.

Каталог перечитывается, когда меняется дата catalog.yaml; габариты моделей считаются один
раз на процесс (кэш по пути и дате файла).
"""

import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import trimesh
import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response

from app.config import settings
from app.events import track
from app.limits import uploads_guard
from app.meshcheck import ALLOWED_EXT, MeshError, MeshInfo, inspect_file
from app.pricing import PricingError, estimate_price, load_pricing
from app.render import render_png
from app.uploads import _save_meta, upload_dir

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # адрес страницы и имя файла превью
PREVIEW_SIZE = 512


class CatalogError(ValueError):
    """Ошибка в catalog.yaml — текст для владельца."""


@dataclass(frozen=True)
class Category:
    slug: str
    title: str
    text: str = ""


@dataclass(frozen=True)
class Model:
    slug: str
    title: str
    category: str
    text: str
    file: str  # имя файла в CATALOG_DIR/models
    material: str = "PLA"  # материал, выбранный в калькуляторе по умолчанию
    license: str = ""  # «Своя модель» или условия лицензии автора

    @property
    def ext(self) -> str:
        return Path(self.file).suffix.lower().lstrip(".")


@dataclass(frozen=True)
class Catalog:
    categories: tuple[Category, ...]
    models: tuple[Model, ...]

    def get(self, slug: str) -> Model | None:
        return next((m for m in self.models if m.slug == slug), None)


# --- чтение catalog.yaml ----------------------------------------------------------------


def catalog_dir() -> Path:
    return settings.catalog_dir


def models_dir() -> Path:
    return catalog_dir() / "models"


def _require(item: dict, key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"catalog.yaml: у {where} не заполнено поле «{key}»")
    return value.strip()


def parse_catalog(raw: dict) -> Catalog:
    """Проверяет структуру yaml: slug'и уникальны и в нужном формате, категории существуют,
    расширения файлов допустимые. Про наличие самих файлов — отдельно, при отдаче."""
    if not isinstance(raw, dict):
        raise CatalogError("catalog.yaml: ожидались разделы categories и models")

    categories: list[Category] = []
    for item in raw.get("categories") or []:
        slug = _require(item, "slug", "категории")
        if not SLUG_RE.match(slug):
            raise CatalogError(f"catalog.yaml: slug категории «{slug}» — только a-z, 0-9 и дефис")
        if any(c.slug == slug for c in categories):
            raise CatalogError(f"catalog.yaml: категория «{slug}» встречается дважды")
        categories.append(Category(slug=slug, title=_require(item, "title", f"категории {slug}"),
                                   text=str(item.get("text") or "").strip()))

    known = {c.slug for c in categories}
    models: list[Model] = []
    for item in raw.get("models") or []:
        slug = _require(item, "slug", "модели")
        if not SLUG_RE.match(slug):
            raise CatalogError(f"catalog.yaml: slug модели «{slug}» — только a-z, 0-9 и дефис")
        if any(m.slug == slug for m in models):
            raise CatalogError(f"catalog.yaml: модель «{slug}» встречается дважды")
        category = _require(item, "category", f"модели {slug}")
        if category not in known:
            raise CatalogError(
                f"catalog.yaml: у модели «{slug}» неизвестная категория «{category}»"
            )
        file = Path(_require(item, "file", f"модели {slug}")).name  # без путей и «../»
        if file.rsplit(".", 1)[-1].lower() not in ALLOWED_EXT:
            raise CatalogError(f"catalog.yaml: у модели «{slug}» файл должен быть stl или 3mf")
        models.append(
            Model(
                slug=slug,
                title=_require(item, "title", f"модели {slug}"),
                category=category,
                text=str(item.get("text") or "").strip(),
                file=file,
                material=str(item.get("material") or "PLA").strip().upper(),
                license=str(item.get("license") or "").strip(),
            )
        )
    return Catalog(categories=tuple(categories), models=tuple(models))


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int) -> Catalog:
    raw = yaml.safe_load(Path(path).read_text("utf-8"))
    return parse_catalog(raw)


def load_catalog() -> Catalog:
    """Читает catalog.yaml; после правки файла перечитает сам (ключ кэша — дата файла)."""
    path = catalog_dir() / "catalog.yaml"
    if not path.is_file():
        raise CatalogError(f"Нет файла каталога: {path}")
    return _load_cached(str(path.resolve()), path.stat().st_mtime_ns)


def model_path(model: Model) -> Path:
    path = models_dir() / model.file
    if not path.is_file():
        raise CatalogError(f"Нет файла модели «{model.slug}»: {path}")
    return path


# --- габариты и превью ------------------------------------------------------------------


@lru_cache(maxsize=256)
def _mesh_info_cached(path: str, mtime_ns: int) -> MeshInfo:
    return inspect_file(Path(path), settings.print_bed)


def mesh_info(model: Model) -> MeshInfo:
    """Габариты, объём, предупреждения — как у клиентской загрузки. Считается один раз."""
    path = model_path(model)
    return _mesh_info_cached(str(path), path.stat().st_mtime_ns)


def preview_path(model: Model) -> Path:
    """Файл кэша превью: slug + дата модели, чтобы новая версия STL получила новую картинку."""
    src = model_path(model)
    return settings.data_dir / "catalog" / "previews" / f"{model.slug}-{src.stat().st_mtime_ns}.png"


def preview_png(model: Model) -> bytes:
    """PNG превью: из кэша, иначе рисуем и кладём в кэш."""
    cached = preview_path(model)
    if cached.is_file():
        return cached.read_bytes()
    mesh = trimesh.load(model_path(model), force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_mesh()
    png = render_png(mesh, PREVIEW_SIZE)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(png)
    return png


# --- ответы API -------------------------------------------------------------------------


def model_card(model: Model) -> dict:
    """Карточка для сайта. Если файл модели или сетка сломаны — карточка без габаритов,
    чтобы одна плохая модель не ломала весь каталог."""
    card = {
        **asdict(model),
        "ext": model.ext,
        "preview_url": f"/api/v1/catalog/{model.slug}/preview.png",
        "file_url": f"/api/v1/catalog/{model.slug}/file",
        "mesh": None,
    }
    try:
        info = mesh_info(model)
    except (CatalogError, MeshError):
        info = None
    card["mesh"] = info.to_dict() if info else None
    card["price"] = price_hint(model, info) if info else None
    return card


def price_hint(model: Model, info: MeshInfo) -> dict | None:
    """Ориентир цены для карточки (UX: цена видна до загрузки файла).

    Считает pricing.estimate_price по объёму сетки в материале модели; материала нет
    в прайсе (смола, «по запросу») — берём PLA. `min_order: true` — одна штука упирается
    в минимальный заказ, сайт пишет «от N ₽». Прайс сломан — карточка просто без цены.
    """
    try:
        pricing = load_pricing()
        material = model.material if model.material in pricing.materials else "PLA"
        if material not in pricing.materials:
            return None
        q = estimate_price(
            pricing, material=material, volume_cm3=info.volume_cm3, surface_cm2=info.surface_cm2
        )
    except (PricingError, OSError, yaml.YAMLError):
        return None
    return {"total": q.total, "material": material, "min_order": q.min_order_applied}


def _catalog_or_500() -> Catalog:
    try:
        return load_catalog()
    except (CatalogError, yaml.YAMLError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _model_or_404(slug: str) -> Model:
    model = _catalog_or_500().get(slug) if SLUG_RE.match(slug) else None
    if model is None:
        raise HTTPException(status_code=404, detail="Модель не найдена.")
    return model


@router.get("")
def get_catalog() -> dict:
    catalog = _catalog_or_500()
    cards = [model_card(m) for m in catalog.models]
    return {
        "categories": [
            {**asdict(c), "count": sum(1 for m in cards if m["category"] == c.slug)}
            for c in catalog.categories
        ],
        "models": cards,
    }


@router.get("/{slug}")
def get_model(slug: str) -> dict:
    return model_card(_model_or_404(slug))


@router.get("/{slug}/preview.png")
async def get_preview(slug: str) -> Response:
    model = _model_or_404(slug)
    try:
        png = await run_in_threadpool(preview_png, model)
    except CatalogError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    # Картинка меняется только вместе с файлом модели (в адресе кэша стоит его дата) —
    # браузеру можно держать её долго.
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{slug}/file")
def get_model_file(slug: str) -> FileResponse:
    model = _model_or_404(slug)
    try:
        path = model_path(model)
    except CatalogError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(
        path, media_type="application/octet-stream", filename=f"{model.slug}.{model.ext}"
    )


@router.post("/{slug}/upload", status_code=201, dependencies=[Depends(uploads_guard)])
async def upload_from_catalog(slug: str) -> dict:
    """Кнопка «Заказать»: делаем из модели каталога обычную загрузку.

    Копия файла нужна, потому что расчёты печати и цены (B04, B05) и заказ (B06) живут
    в папке загрузки; владелец может менять модель в каталоге, а у заказа останется
    та версия, которую видел клиент. Автоудаление (B15) к таким копиям применяется так же.
    """
    model = _model_or_404(slug)
    try:
        src = model_path(model)
        info = await run_in_threadpool(mesh_info, model)
    except CatalogError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except MeshError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    upload_id = uuid.uuid4().hex
    folder = upload_dir(upload_id)
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(src, folder / f"model.{model.ext}")
    meta = {
        "id": upload_id,
        "original_name": f"{model.title}.{model.ext}",
        "ext": model.ext,
        "size_bytes": src.stat().st_size,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "units": "mm",
        "mesh": info.to_dict(),
        # Откуда взялась загрузка — видно в meta.json и в событиях воронки.
        "source": "catalog",
        "catalog": {"slug": model.slug, "title": model.title, "material": model.material},
    }
    _save_meta(folder, meta)
    await run_in_threadpool(
        track,
        "upload",
        upload_id=upload_id,
        props={
            "ext": model.ext,
            "size_bytes": meta["size_bytes"],
            "watertight": info.watertight,
            "warnings": info.warnings,
            "source": "catalog",
            "catalog_slug": model.slug,
        },
    )
    return meta


def reload_catalog() -> None:
    """Сброс кэшей — для тестов."""
    _load_cached.cache_clear()
    _mesh_info_cached.cache_clear()

