"""Раскраска модели по частям (B31).

Клиент открыл страницу загруженной модели (своей, из каталога, из редактора или с тиснением)
и хочет напечатать её в нескольких цветах: каждую отдельную деталь — своим пластиком.
Результат — новая загрузка: файл 3MF, где каждая деталь — отдельный объект со своим
цветом (стандартные `basematerials` формата 3MF; PrusaSlicer и 3D-просмотр на сайте их
понимают). Дальше расчёт печати, цена, заказ — как у любой загрузки. Цена от количества
цветов не зависит (docs/DECISIONS.md).

Что такое «деталь»: кусок сетки, треугольники которого соединены общими рёбрами
(связная компонента). Корпус и крышка, кольцо и брелок — разные детали. Цельная модель —
одна деталь, её можно только целиком покрасить в один цвет. Мелких деталей бывает много
(сотни бусин) — показываем не больше MAX_PARTS: самые крупные по объёму отдельно,
остальные одной строкой «Мелкие детали».

Как устроено:
1. GET …/parts разбирает модель на детали (trimesh.split), складывает их подряд в
   paint/parts.stl и запоминает, с какого треугольника начинается каждая (parts.json).
   3D-просмотр на сайте грузит именно parts.stl (…/parts/file) и красит треугольники по этим
   диапазонам — порядок треугольников в STL сервер и браузер читают одинаково.
2. POST …/paints с цветами по деталям → сборка 3MF (в очереди worker или, без REDIS_URL,
   сразу) → новая загрузка с source = "paint".

GET  /api/v1/paint/colors                    — палитра из config/colors.yaml + лимит деталей.
GET  /api/v1/uploads/{id}/parts              — детали модели (считаются один раз, кэш в файле).
GET  /api/v1/uploads/{id}/parts/file         — STL, где детали лежат подряд (для 3D-просмотра).
POST /api/v1/uploads/{id}/paints             — тело {"colors": ["red", "blue", …]} — по коду цвета
                                               на каждую деталь по порядку; 422 с ошибками.
GET  /api/v1/uploads/{id}/paints/{job_id}    — статус queued|running|done|error; после done —
                                               result_upload_id: id новой загрузки.

Файлы лежат в DATA_DIR/uploads/<id>/paint/ и удаляются вместе с загрузкой (app/cleanup.py)
и при смене единиц мм/дюймы (app/uploads.py).
"""

import hashlib
import io
import json
import logging
import re
import uuid
import zipfile
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import trimesh
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import jobs
from app.config import settings
from app.emboss import EmbossError, load_model
from app.events import track
from app.limits import uploads_guard
from app.meshcheck import MeshError, inspect_file
from app.uploads import _save_meta, load_meta, upload_dir

log = logging.getLogger(__name__)

router = APIRouter(tags=["paint"])

MAX_PARTS = 12  # сколько деталей показываем отдельно; остальные — одной строкой
SMALL_NAME = "Мелкие детали"
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")  # код цвета в colors.yaml
HEX_RE = re.compile(r"^#[0-9A-F]{6}$")
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class PaintError(ValueError):
    """Раскраска не получилась — текст для клиента (или для владельца про colors.yaml)."""


# --- палитра ----------------------------------------------------------------------------


def parse_colors(raw: object) -> list[dict]:
    """Содержимое colors.yaml → список {key, name, hex}. Ошибки в файле — PaintError."""
    items = raw.get("colors") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        raise PaintError("В файле цветов нет списка colors.")
    colors: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise PaintError("Каждый цвет — строка вида { key, name, hex }.")
        key = str(item.get("key", "")).strip()
        name = str(item.get("name", "")).strip()
        hex_ = str(item.get("hex", "")).strip().upper()
        if not KEY_RE.match(key):
            raise PaintError(f"Код цвета «{key}» — только латиница, цифры, «-» и «_».")
        if key in seen:
            raise PaintError(f"Код цвета «{key}» встречается дважды.")
        if not name:
            raise PaintError(f"У цвета «{key}» нет названия (name).")
        if not HEX_RE.match(hex_):
            raise PaintError(f"У цвета «{key}» hex должен быть вида #RRGGBB.")
        seen.add(key)
        colors.append({"key": key, "name": name, "hex": hex_})
    return colors


@lru_cache
def _load_colors_cached(path: str) -> tuple[dict, ...]:
    return tuple(parse_colors(yaml.safe_load(Path(path).read_text("utf-8"))))


def load_colors(path: Path | None = None) -> list[dict]:
    """Читает colors.yaml один раз на процесс (кэш по пути). Сменил файл — перезапусти API."""
    path = path or settings.colors_path
    if not Path(path).is_file():
        raise PaintError(f"Нет файла с цветами: {path}")
    return [dict(c) for c in _load_colors_cached(str(Path(path).resolve()))]


def reload_colors() -> None:
    """Сброс кэша — для тестов."""
    _load_colors_cached.cache_clear()


# --- детали модели ----------------------------------------------------------------------


def paint_dir(upload_id: str) -> Path:
    return upload_dir(upload_id) / "paint"


def parts_path(upload_id: str) -> Path:
    return paint_dir(upload_id) / "parts.json"


def parts_file(upload_id: str) -> Path:
    return paint_dir(upload_id) / "parts.stl"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def split_parts(mesh: trimesh.Trimesh) -> list[trimesh.Trimesh]:
    """Связные куски сетки, крупные (по объёму) первыми. Больше MAX_PARTS — хвост склеен в один
    кусок с metadata["merged_count"] = сколько мелких деталей в нём."""
    pieces = [p for p in mesh.split(only_watertight=False) if len(p.faces) > 0]
    if not pieces:
        pieces = [mesh]
    pieces.sort(key=lambda p: (abs(float(p.volume)), len(p.faces)), reverse=True)
    if len(pieces) > MAX_PARTS:
        tail = pieces[MAX_PARTS - 1 :]
        rest = trimesh.util.concatenate(tail)
        rest.metadata["merged_count"] = len(tail)
        pieces = pieces[: MAX_PARTS - 1] + [rest]
    return pieces


def build_parts(upload_id: str, meta: dict) -> dict:
    """Разбирает модель на детали, пишет paint/parts.stl (детали подряд) и parts.json."""
    model_file = upload_dir(upload_id) / f"model.{meta['ext']}"
    mesh = load_model(model_file, meta.get("units", "mm"))  # в мм, дыры закрыты
    pieces = split_parts(mesh)
    parts: list[dict] = []
    offset = 0
    for i, piece in enumerate(pieces):
        merged = int(piece.metadata.get("merged_count", 0))
        ext = [float(v) for v in piece.extents]
        parts.append(
            {
                "index": i,
                "name": f"{SMALL_NAME} ({merged} шт.)" if merged else f"Деталь {i + 1}",
                "faces": int(len(piece.faces)),
                "first_face": offset,  # первый треугольник детали в parts.stl
                "volume_cm3": round(abs(float(piece.volume)) / 1000.0, 3),
                "bbox_mm": {k: round(v, 2) for k, v in zip("xyz", ext, strict=True)},
                "merged": merged,
            }
        )
        offset += int(len(piece.faces))
    whole = trimesh.util.concatenate(pieces) if len(pieces) > 1 else pieces[0]
    folder = paint_dir(upload_id)
    folder.mkdir(parents=True, exist_ok=True)
    parts_file(upload_id).write_bytes(whole.export(file_type="stl"))
    record = {
        "upload_id": upload_id,
        "units": meta.get("units", "mm"),
        "created_at": _now(),
        "triangles": offset,
        "max_parts": MAX_PARTS,
        "parts": parts,
    }
    parts_path(upload_id).write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


def load_parts(upload_id: str, meta: dict) -> dict | None:
    """Готовая разборка, если она есть и сделана для текущих единиц модели."""
    path = parts_path(upload_id)
    if not path.is_file():
        return None
    record = json.loads(path.read_text("utf-8"))
    if record.get("units") != meta.get("units", "mm") or not parts_file(upload_id).is_file():
        return None
    return record


def ensure_parts(upload_id: str, meta: dict) -> dict:
    record = load_parts(upload_id, meta)
    if record is None:
        try:
            record = build_parts(upload_id, meta)
        except (EmbossError, MeshError) as e:
            raise PaintError(str(e)) from e
    return record


# --- проверка цветов --------------------------------------------------------------------


def validate_colors(raw: object, parts_count: int, palette: list[dict]) -> tuple[list[str], dict]:
    """Список кодов цветов от клиента → (чистый список; ошибки по полям)."""
    if not isinstance(raw, list):
        return [], {"colors": "Ожидался список цветов — по одному на каждую деталь."}
    if len(raw) != parts_count:
        return [], {"colors": f"Нужно {parts_count} цветов — по одному на каждую деталь."}
    keys = {c["key"] for c in palette}
    clean: list[str] = []
    for value in raw:
        if not isinstance(value, str) or value not in keys:
            return [], {"colors": f"Нет такого цвета: «{value}». Выберите из списка."}
        clean.append(value)
    return clean, {}


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def describe(parts: list[dict], colors: list[str], palette: dict[str, dict]) -> str:
    """«Деталь 1 — красный, Деталь 2 — синий»; всё одним цветом — «вся модель — красный»."""
    names = [palette[c]["name"].lower() for c in colors]
    if len(set(names)) == 1:
        return f"вся модель — {names[0]}"
    return ", ".join(f"{p['name']} — {n}" for p, n in zip(parts, names, strict=True))


def build_result_name(original_name: str, colors: list[str], palette: dict[str, dict]) -> str:
    """«bracket.stl» + 2 цвета → «bracket — 2 цвета.3mf»; один цвет → «bracket — красный.3mf»."""
    stem = Path(original_name).stem[:120] or "model"
    distinct = list(dict.fromkeys(palette[c]["name"].lower() for c in colors))
    if len(distinct) == 1:
        what = distinct[0]
    else:
        n = len(distinct)
        what = f"{n} {_plural(n, 'цвет', 'цвета', 'цветов')}"
    return f"{stem} — {what}.3mf"[:200]


# --- записи сборок ----------------------------------------------------------------------


def job_path(upload_id: str, job_id: str) -> Path:
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    return paint_dir(upload_id) / f"{job_id}.json"


def job_id_for(upload_id: str, parts: dict, colors: list[str]) -> str:
    """Та же модель (единицы, разборка), те же цвета → та же сборка."""
    key = json.dumps(
        [upload_id, parts["units"], parts["triangles"], len(parts["parts"]), colors],
        ensure_ascii=False,
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def load_job(upload_id: str, job_id: str) -> dict | None:
    path = job_path(upload_id, job_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text("utf-8"))


def save_job(record: dict) -> dict:
    path = job_path(record["upload_id"], record["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


def new_job(upload_id: str, job_id: str, colors: list[str]) -> dict:
    return {
        "id": job_id,
        "upload_id": upload_id,
        "colors": colors,
        "status": "queued",
        "attempt": 0,  # номер попытки; растёт, если прежняя задача была брошена (app/jobs.py)
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "result_upload_id": None,  # id новой загрузки (3MF в цветах)
    }


# --- файл 3MF ---------------------------------------------------------------------------

CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" '
    'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>"
)
RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)


def _attr(text: str) -> str:
    return escape(text, {'"': "&quot;"})


def write_3mf(objects: list[dict], title: str = "") -> bytes:
    """Собирает 3MF: objects — [{"name", "vertices" (n×3), "faces" (m×3), "color": {key, name,
    hex}}]. Каждый объект — отдельная деталь со своим цветом из basematerials (ядро формата
    3MF, без расширений — читают PrusaSlicer, Cura и three.js)."""
    materials: list[dict] = []
    index: dict[str, int] = {}
    for obj in objects:
        key = obj["color"]["key"]
        if key not in index:
            index[key] = len(materials)
            materials.append(obj["color"])

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="ru-RU" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
    ]
    if title:
        out.append(f'<metadata name="Title">{escape(title)}</metadata>')
    out.append('<resources><basematerials id="1">')
    for m in materials:
        out.append(f'<base name="{_attr(m["name"])}" displaycolor="{m["hex"]}FF"/>')
    out.append("</basematerials>")
    for i, obj in enumerate(objects):
        oid = i + 2  # id 1 занят палитрой
        pindex = index[obj["color"]["key"]]
        out.append(
            f'<object id="{oid}" name="{_attr(obj["name"])}" type="model" '
            f'pid="1" pindex="{pindex}"><mesh><vertices>'
        )
        vertices = np.asarray(obj["vertices"], dtype=np.float64).tolist()
        out.append(
            "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in vertices)
        )
        out.append("</vertices><triangles>")
        faces = np.asarray(obj["faces"], dtype=np.int64).tolist()
        out.append("".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces))
        out.append("</triangles></mesh></object>")
    out.append("</resources><build>")
    out.extend(f'<item objectid="{i + 2}"/>' for i in range(len(objects)))
    out.append("</build></model>")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", RELS_XML)
        zf.writestr("3D/3dmodel.model", "".join(out))
    return buf.getvalue()


def part_meshes(upload_id: str, parts: dict) -> list[trimesh.Trimesh]:
    """Детали из parts.stl по диапазонам треугольников — в том же порядке, что в parts.json."""
    mesh = trimesh.load(parts_file(upload_id), file_type="stl", force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) != parts["triangles"]:
        raise PaintError("Разборка модели устарела — обновите страницу и раскрасьте заново.")
    pieces = []
    for part in parts["parts"]:
        ids = np.arange(part["first_face"], part["first_face"] + part["faces"])
        piece = mesh.submesh([ids], append=True, repair=False)
        piece.merge_vertices()  # в STL каждый треугольник со своими вершинами — ужимаем
        pieces.append(piece)
    return pieces


def run_paint(upload_id: str, job_id: str) -> dict:
    """Сама работа (в worker или прямо в API без очереди): детали → 3MF → новая загрузка."""
    record = load_job(upload_id, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    record.update(status="running", started_at=_now())
    save_job(record)
    colors: list[str] = record["colors"]
    try:
        meta = load_meta(upload_id)
        parts = ensure_parts(upload_id, meta)
        palette = {c["key"]: c for c in load_colors()}
        if len(colors) != len(parts["parts"]) or any(c not in palette for c in colors):
            raise PaintError("Список деталей или цветов изменился — раскрасьте заново.")
        pieces = part_meshes(upload_id, parts)
        objects = [
            {
                "name": part["name"],
                "vertices": piece.vertices,
                "faces": piece.faces,
                "color": palette[color],
            }
            for part, piece, color in zip(parts["parts"], pieces, colors, strict=True)
        ]
        original_name = meta.get("original_name", "model.stl")
        data = write_3mf(objects, title=Path(original_name).stem)

        new_id = uuid.uuid4().hex
        folder = upload_dir(new_id)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "model.3mf").write_bytes(data)
        info = inspect_file(folder / "model.3mf", settings.print_bed)
        distinct = list(dict.fromkeys(colors))
        new_meta = {
            "id": new_id,
            "original_name": build_result_name(original_name, colors, palette),
            "ext": "3mf",
            "size_bytes": len(data),
            "created_at": _now(),
            "units": "mm",
            "mesh": info.to_dict(),
            "source": "paint",
            # Откуда модель и как покрашена — видно на странице загрузки и в заказе.
            "paint": {
                "parent_id": upload_id,
                "parent_name": original_name,
                "job_id": job_id,
                "parts": [
                    {
                        "name": part["name"],
                        "color": color,
                        "color_name": palette[color]["name"],
                        "hex": palette[color]["hex"],
                    }
                    for part, color in zip(parts["parts"], colors, strict=True)
                ],
                "colors": [palette[c] for c in distinct],
                "summary": describe(parts["parts"], colors, palette),
            },
        }
        # Материал из каталога/редактора/тиснения наследуем — калькулятор подставит его.
        for key in ("catalog", "editor", "emboss"):
            if meta.get(key) and meta[key].get("material"):
                new_meta["paint"]["material"] = meta[key]["material"]
        _save_meta(folder, new_meta)
        track(
            "upload",
            upload_id=new_id,
            props={
                "ext": "3mf",
                "size_bytes": len(data),
                "watertight": info.watertight,
                "warnings": info.warnings,
                "source": "paint",
                "parent_upload_id": upload_id,
                "job_id": job_id,
                "parts": len(colors),
                "colors": len(distinct),
            },
        )
        record.update(status="done", error=None, result_upload_id=new_id)
    except (PaintError, MeshError, OSError, ValueError) as e:
        record.update(status="error", error=str(e))
    except HTTPException as e:
        record.update(status="error", error=str(e.detail))
    record["finished_at"] = _now()
    return save_job(record)


# --- API --------------------------------------------------------------------------------


class PaintRequest(BaseModel):
    colors: list = []


async def _enqueue(request: Request, upload_id: str, job_id: str, attempt: int = 0) -> None:
    arq_id = jobs.retry_job_id(f"paint:{upload_id}:{job_id}", attempt)
    await jobs.enqueue(request, "paint_upload", upload_id, job_id, job_id=arq_id)


@router.get("/api/v1/paint/colors")
def paint_colors() -> dict:
    """Палитра для формы на сайте."""
    try:
        colors = load_colors()
    except PaintError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"colors": colors, "max_parts": MAX_PARTS}


@router.get("/api/v1/uploads/{upload_id}/parts")
async def get_parts(upload_id: str) -> dict:
    meta = load_meta(upload_id)
    try:
        return await run_in_threadpool(ensure_parts, upload_id, meta)
    except PaintError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/api/v1/uploads/{upload_id}/parts/file")
def get_parts_file(upload_id: str) -> FileResponse:
    meta = load_meta(upload_id)
    if load_parts(upload_id, meta) is None:
        raise HTTPException(status_code=404, detail="Модель ещё не разобрана на детали.")
    return FileResponse(parts_file(upload_id), media_type="application/octet-stream")


@router.post(
    "/api/v1/uploads/{upload_id}/paints",
    status_code=202,
    dependencies=[Depends(uploads_guard)],
)
async def create_paint(upload_id: str, body: PaintRequest, request: Request) -> dict:
    meta = load_meta(upload_id)
    try:
        parts = await run_in_threadpool(ensure_parts, upload_id, meta)
        palette = load_colors()
    except PaintError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    colors, errors = validate_colors(body.colors, len(parts["parts"]), palette)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    job_id = job_id_for(upload_id, parts, colors)
    record = jobs.settle(load_job(upload_id, job_id), save_job)  # брошенная → error
    cached = record is not None and record["status"] in ("queued", "running", "done")
    await run_in_threadpool(
        track,
        "paint_build",
        upload_id=upload_id,
        props={
            "job_id": job_id,
            "cached": cached,
            "parts": len(colors),
            "colors": len(set(colors)),
        },
    )
    if cached:
        return record

    attempt = jobs.next_attempt(record)
    record = new_job(upload_id, job_id, colors)
    record["attempt"] = attempt
    save_job(record)
    if settings.redis_url:
        try:
            await _enqueue(request, upload_id, job_id, attempt)
        except jobs.QueueUnavailable:
            job_path(upload_id, job_id).unlink(missing_ok=True)
            raise jobs.queue_unavailable() from None
        return record
    # Без очереди — строим здесь же (разработка и тесты).
    return await run_in_threadpool(run_paint, upload_id, job_id)


@router.get("/api/v1/uploads/{upload_id}/paints/{job_id}")
def get_paint(upload_id: str, job_id: str) -> dict:
    load_meta(upload_id)
    record = jobs.settle(load_job(upload_id, job_id), save_job)
    if record is None:
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    return record
