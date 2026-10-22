"""Тиснение надписи или логотипа на загруженной модели (B30).

Клиент загрузил модель (или взял её из каталога / построил в редакторе), открыл её страницу и
хочет нанести на одну из граней надпись или свой логотип (SVG) — выпуклые или углублённые.
Результат — новая обычная загрузка (копия модели с тиснением): дальше расчёт печати, цена,
заказ — как у любой загрузки. Исходная загрузка не меняется, к ней можно вернуться.

Как строится:
1. OpenSCAD (app/scad/emboss.scad) делает само тиснение — плоскую фигуру (text() или
   import() SVG), вытянутую в толщину. Это быстро: модель клиента OpenSCAD не трогает.
2. Python (trimesh + manifold3d) ставит фигуру на нужную грань — по центру
   ограничивающего параллелепипеда, со сдвигом dx/dy — и соединяет с моделью:
   выпуклое тиснение прибавляет (union), углублённое вырезает (difference).
   Почему не всё в OpenSCAD — см. docs/DECISIONS.md (CGAL в OpenSCAD 2021 считает
   такие операции на больших сетках минутами и падает на незамкнутых).

POST   /api/v1/uploads/{id}/logo              — загрузить SVG-логотип (≤ 1 МБ) к загрузке.
DELETE /api/v1/uploads/{id}/logo              — убрать логотип.
POST   /api/v1/uploads/{id}/embosses          — тело {"params": {...}}: проверка параметров
                                                (422 с ошибками по полям), сборка. Одинаковые
                                                параметры → одна и та же сборка. В очередь
                                                (worker) или, без REDIS_URL, сразу.
GET    /api/v1/uploads/{id}/embosses/{job_id} — статус queued|running|done|error; после done —
                                                result_upload_id: id новой загрузки.
GET    /api/v1/emboss/options                 — границы и варианты параметров для формы.

Сборки лежат в DATA_DIR/uploads/<id>/embosses/<job_id>.json (+ <job_id>.stl — само тиснение);
удаляются вместе с загрузкой (app/cleanup.py). Результат — обычная папка загрузки с
meta.json, где source = "emboss" и parent — исходная загрузка.
"""

import hashlib
import json
import logging
import math
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import trimesh
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from lxml import etree
from pydantic import BaseModel

from app.config import settings
from app.events import track
from app.meshcheck import UNITS, MeshError, inspect_file
from app.openscad import OpenScadError, run_openscad
from app.uploads import _save_meta, load_meta, upload_dir

log = logging.getLogger(__name__)

router = APIRouter(tags=["emboss"])

SCAD_PATH = Path(__file__).parent / "scad" / "emboss.scad"
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")

KINDS = ("text", "logo")
FONTS = ("sans", "serif", "mono")
STYLES = ("raised", "engraved")
# Грань модели: по ограничивающему параллелепипеду, «спереди» = сторона −Y (ближняя к зрителю
# в 3D-просмотре), «справа» = +X, «сверху» = +Z.
FACES = ("top", "bottom", "front", "back", "left", "right")
FACE_LABELS = {
    "top": "сверху",
    "bottom": "снизу",
    "front": "спереди",
    "back": "сзади",
    "left": "слева",
    "right": "справа",
}
FONT_LABELS = {"sans": "без засечек", "serif": "с засечками", "mono": "моноширинный"}
TEXT_MAXLEN = 40
SIZE_MIN, SIZE_MAX = 3.0, 200.0  # мм: высота букв или ширина логотипа
DEPTH_MIN, DEPTH_MAX = 0.2, 10.0  # мм: высота выпуклого / глубина углублённого
SHIFT_MAX = 500.0  # мм: сдвиг от центра грани
MAX_LOGO_BYTES = 1024 * 1024
# В SVG не должно быть ни скриптов, ни ссылок на внешние файлы; текст OpenSCAD не рисует —
# его нужно перевести в кривые в редакторе (Inkscape: «Контур → Оконтурить объект»).
SVG_FORBIDDEN = {"script", "image", "foreignObject", "use", "a"}
SVG_TEXT = {"text", "tspan", "textPath"}
SVG_SHAPES = {"path", "rect", "circle", "ellipse", "polygon", "polyline"}

DEFAULTS = {
    "kind": "text",
    "text": "",
    "font": "sans",
    "bold": True,
    "size_mm": 10.0,
    "depth_mm": 1.0,
    "style": "raised",
    "face": "front",
    "dx": 0.0,
    "dy": 0.0,
    "angle": 0.0,
}


class EmbossError(ValueError):
    """Тиснение не получилось — текст для клиента."""


# --- SVG-логотип ------------------------------------------------------------------------


def _local(tag: object) -> str:
    """«{http://www.w3.org/2000/svg}path» → «path»; комментарии и т.п. — пустая строка."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def check_svg(data: bytes) -> str | None:
    """Проверяет SVG-логотип. Возвращает текст ошибки или None, если файл годится."""
    if len(data) > MAX_LOGO_BYTES:
        return "Логотип больше 1 МБ."
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError:
        return "Не удалось прочитать файл как SVG."
    if _local(root.tag) != "svg":
        return "Нужен файл SVG (векторная картинка)."
    shapes = 0
    for el in root.iter():
        tag = _local(el.tag)
        if tag in SVG_FORBIDDEN or any(_local(a).lower() == "href" for a in el.attrib):
            return "В SVG не должно быть скриптов, картинок и ссылок — только контуры."
        if tag in SVG_TEXT:
            return (
                "Текст в SVG нужно перевести в кривые (в Inkscape: «Контур → Оконтурить "
                "объект»), иначе он не напечатается."
            )
        if tag in SVG_SHAPES:
            shapes += 1
    if shapes == 0:
        return "В SVG нет контуров — нечего наносить."
    return None


def logo_path(upload_id: str) -> Path:
    return upload_dir(upload_id) / "logo.svg"


@router.post("/api/v1/uploads/{upload_id}/logo")
async def upload_logo(upload_id: str, file: UploadFile) -> dict:
    """Загрузить SVG-логотип к модели. Один логотип на загрузку; новый заменяет старый."""
    meta = load_meta(upload_id)
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="Логотип больше 1 МБ.")
    if not data:
        raise HTTPException(status_code=422, detail="Пустой файл.")
    error = check_svg(data)
    if error:
        raise HTTPException(status_code=422, detail=error)
    logo_path(upload_id).write_bytes(data)
    name = Path(file.filename or "logo.svg").name[:200] or "logo.svg"
    meta["logo"] = {"name": name, "size_bytes": len(data)}
    _save_meta(upload_dir(upload_id), meta)
    return meta


@router.delete("/api/v1/uploads/{upload_id}/logo")
def delete_logo(upload_id: str) -> dict:
    meta = load_meta(upload_id)
    logo_path(upload_id).unlink(missing_ok=True)
    meta.pop("logo", None)
    _save_meta(upload_dir(upload_id), meta)
    return meta


# --- проверка параметров ----------------------------------------------------------------


def _number(value: object, lo: float, hi: float, unit: str = "мм") -> tuple[float | None, str]:
    if isinstance(value, bool):
        return None, "Нужно число."
    if isinstance(value, str):
        try:
            value = float(value.replace(",", ".").strip())
        except ValueError:
            return None, "Нужно число."
    if not isinstance(value, int | float) or not math.isfinite(value):
        return None, "Нужно число."
    if value < lo:
        return None, f"Не меньше {lo:g} {unit}."
    if value > hi:
        return None, f"Не больше {hi:g} {unit}."
    return round(float(value), 2), ""


def validate_params(raw: dict | None, has_logo: bool) -> tuple[dict, dict[str, str]]:
    """Параметры тиснения от клиента → (чистые, с умолчаниями; ошибки по полям)."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return {}, {"params": "Ожидался словарь параметров."}
    clean: dict = {}
    errors: dict[str, str] = {}
    for name in raw:
        if name not in DEFAULTS:
            errors[str(name)] = "Неизвестный параметр."
    values = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}

    for name, options in (("kind", KINDS), ("font", FONTS), ("style", STYLES), ("face", FACES)):
        if str(values[name]) not in options:
            errors[name] = "Выберите один из вариантов."
        else:
            clean[name] = str(values[name])

    bold = values["bold"]
    if isinstance(bold, bool) or bold in ("true", "false", 0, 1):
        clean["bold"] = bold if isinstance(bold, bool) else bold in ("true", 1)
    else:
        errors["bold"] = "Нужно да или нет."

    for name, lo, hi, unit in (
        ("size_mm", SIZE_MIN, SIZE_MAX, "мм"),
        ("depth_mm", DEPTH_MIN, DEPTH_MAX, "мм"),
        ("dx", -SHIFT_MAX, SHIFT_MAX, "мм"),
        ("dy", -SHIFT_MAX, SHIFT_MAX, "мм"),
        ("angle", -180.0, 180.0, "°"),
    ):
        num, error = _number(values[name], lo, hi, unit)
        if error:
            errors[name] = error
        else:
            clean[name] = num

    text = values["text"]
    if not isinstance(text, str):
        errors["text"] = "Нужен текст."
    else:
        text = " ".join(text.split())  # лишние пробелы и переносы строк — в один пробел
        if len(text) > TEXT_MAXLEN:
            errors["text"] = f"Не длиннее {TEXT_MAXLEN} символов."
        elif clean.get("kind") == "text" and not text:
            errors["text"] = "Введите надпись."
        else:
            clean["text"] = text if clean.get("kind") == "text" else ""
    if clean.get("kind") == "logo" and not has_logo:
        errors["kind"] = "Сначала загрузите логотип (SVG)."
    return clean, errors


def _fmt(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def describe(params: dict, logo_name: str = "") -> str:
    """Параметры словами: «Надпись «ТУЦ» (без засечек, жирный) 10 мм, выпуклая 1 мм, спереди»."""
    if params["kind"] == "logo":
        what = f"Логотип {logo_name or 'SVG'} шириной {_fmt(params['size_mm'])} мм"
        how = "выпуклый" if params["style"] == "raised" else "углублённый"
    else:
        font = FONT_LABELS[params["font"]] + (", жирный" if params["bold"] else "")
        what = f"Надпись «{params['text']}» ({font}) {_fmt(params['size_mm'])} мм"
        how = "выпуклая" if params["style"] == "raised" else "углублённая"
    parts = [what, f"{how} {_fmt(params['depth_mm'])} мм", FACE_LABELS[params["face"]]]
    if params["dx"] or params["dy"]:
        parts.append(f"сдвиг {_fmt(params['dx'])} / {_fmt(params['dy'])} мм")
    if params["angle"]:
        parts.append(f"поворот {_fmt(params['angle'])}°")
    return ", ".join(parts)


# --- записи сборок ----------------------------------------------------------------------


def jobs_dir(upload_id: str) -> Path:
    return upload_dir(upload_id) / "embosses"


def job_path(upload_id: str, job_id: str) -> Path:
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    return jobs_dir(upload_id) / f"{job_id}.json"


def decoration_path(upload_id: str, job_id: str) -> Path:
    return jobs_dir(upload_id) / f"{job_id}.stl"


def job_id_for(upload_id: str, meta: dict, params: dict) -> str:
    """Та же модель (файл, единицы), тот же логотип, те же параметры → та же сборка."""
    logo = logo_path(upload_id)
    key = json.dumps(
        [
            upload_id,
            meta.get("units", "mm"),
            logo.stat().st_mtime_ns if params["kind"] == "logo" and logo.is_file() else 0,
            params,
        ],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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


def new_job(upload_id: str, job_id: str, params: dict) -> dict:
    return {
        "id": job_id,
        "upload_id": upload_id,
        "params": params,
        "status": "queued",
        "created_at": _now(),
        "finished_at": None,
        "error": None,
        "warnings": [],  # "merged_without_boolean" — выпуклое тиснение просто приложено
        "result_upload_id": None,  # id новой загрузки с тиснением
    }


# --- геометрия --------------------------------------------------------------------------


def face_transform(bounds: np.ndarray, face: str, dx: float, dy: float) -> np.ndarray:
    """Матрица 4×4: фигуру из плоскости XY (лицом вверх, центр в нуле) — на грань модели.

    bounds — [[min x, y, z], [max x, y, z]] модели. Фигура встаёт в центр грани, dx — вправо,
    dy — вверх, если смотреть на эту грань снаружи. Текст читается снаружи.
    """
    lo, hi = bounds
    c = (lo + hi) / 2
    rx = trimesh.transformations.rotation_matrix
    x, z = (1, 0, 0), (0, 0, 1)
    rotations = {
        "top": np.eye(4),
        "bottom": rx(math.pi, x),
        "front": rx(math.pi / 2, x),
        "back": rx(math.pi, z) @ rx(math.pi / 2, x),
        "right": rx(math.pi / 2, z) @ rx(math.pi / 2, x),
        "left": rx(-math.pi / 2, z) @ rx(math.pi / 2, x),
    }
    positions = {
        "top": (c[0], c[1], hi[2]),
        "bottom": (c[0], c[1], lo[2]),
        "front": (c[0], lo[1], c[2]),
        "back": (c[0], hi[1], c[2]),
        "right": (hi[0], c[1], c[2]),
        "left": (lo[0], c[1], c[2]),
    }
    tr = trimesh.transformations.translation_matrix
    return tr(positions[face]) @ rotations[face] @ tr((dx, dy, 0))


def load_model(path: Path, units: str) -> trimesh.Trimesh:
    """Модель клиента в мм: STL или 3MF (несколько объектов склеиваем), дыры закрываем."""
    try:
        loaded = trimesh.load(path, file_type=path.suffix.lstrip("."), force="mesh")
    except Exception as e:  # noqa: BLE001 — trimesh кидает разное
        raise EmbossError("Не удалось прочитать модель.") from e
    if isinstance(loaded, trimesh.Scene):
        loaded = loaded.to_mesh()
    if not isinstance(loaded, trimesh.Trimesh) or loaded.is_empty:
        raise EmbossError("В модели нет геометрии.")
    mesh: trimesh.Trimesh = loaded
    if UNITS.get(units, 1.0) != 1.0:
        mesh.apply_scale(UNITS[units])
    mesh.merge_vertices()
    if not mesh.is_watertight:
        trimesh.repair.fill_holes(mesh)
    if mesh.is_watertight:
        # Нормали наружу: иначе объединение и вырез дадут «вывернутый» результат.
        trimesh.repair.fix_normals(mesh)
    return mesh


def _boolean(op: str, model: trimesh.Trimesh, dec: trimesh.Trimesh) -> trimesh.Trimesh | None:
    """union / difference через manifold3d. None — если не вышло (сетка не замкнута и т.п.)."""
    try:
        fn = trimesh.boolean.union if op == "union" else trimesh.boolean.difference
        result = fn([model, dec], engine="manifold")
    except Exception as e:  # noqa: BLE001 — manifold кидает свои исключения
        log.warning("emboss %s failed: %s", op, e)
        return None
    if not isinstance(result, trimesh.Trimesh) or result.is_empty or len(result.faces) == 0:
        return None
    # Пустая или «съеденная» модель — тоже неудача: у manifold незамкнутая сетка = пустая.
    if abs(float(result.volume)) < 0.5 * abs(float(model.volume)):
        return None
    return result


def merge(model: trimesh.Trimesh, dec: trimesh.Trimesh, style: str) -> tuple[trimesh.Trimesh, list]:
    """Соединяет модель и тиснение. Возвращает (сетка, предупреждения)."""
    # Булевы операции работают только на замкнутой сетке с согласованными нормалями.
    if model.is_watertight and model.is_winding_consistent:
        result = _boolean("difference" if style == "engraved" else "union", model, dec)
        if result is not None:
            return result, []
    if style == "engraved":
        raise EmbossError(
            "Углубить не получилось: сетка модели не замкнута (есть дыры). Попробуйте "
            "выпуклое тиснение или исправьте модель."
        )
    # Незамкнутую модель всё равно можно напечатать с выпуклой надписью: слайсер объединит
    # пересекающиеся тела сам. Просто кладём обе сетки в один файл.
    return trimesh.util.concatenate([model, dec]), ["merged_without_boolean"]


def _scad_params(params: dict, upload_id: str) -> dict:
    return {
        "kind": params["kind"],
        "text": params["text"],
        "font": params["font"],
        "bold": params["bold"],
        "size_mm": params["size_mm"],
        "depth_mm": params["depth_mm"],
        "style": params["style"],
        "logo_file": str(logo_path(upload_id).resolve()) if params["kind"] == "logo" else "",
        "angle": params["angle"],
    }


def build_result_name(original_name: str, params: dict) -> str:
    """«bracket.stl» + надпись «ТУЦ» → «bracket + ТУЦ.stl»; логотип → «bracket + логотип.stl»."""
    stem = Path(original_name).stem[:120] or "model"
    what = f"«{params['text']}»" if params["kind"] == "text" else "логотип"
    return f"{stem} + {what}.stl"[:200]


def run_emboss(upload_id: str, job_id: str) -> dict:
    """Сама работа (в worker или прямо в API без очереди): OpenSCAD → тиснение → модель."""
    record = load_job(upload_id, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    record["status"] = "running"
    save_job(record)
    params = record["params"]
    try:
        meta = load_meta(upload_id)
        dec_file = decoration_path(upload_id, job_id)
        run_openscad(SCAD_PATH, dec_file, _scad_params(params, upload_id))
        dec = trimesh.load(dec_file, file_type="stl", force="mesh")
        if not isinstance(dec, trimesh.Trimesh) or dec.is_empty:
            raise EmbossError("Тиснение получилось пустым — проверьте надпись или логотип.")
        model_file = upload_dir(upload_id) / f"model.{meta['ext']}"
        model = load_model(model_file, meta.get("units", "mm"))
        matrix = face_transform(model.bounds, params["face"], params["dx"], params["dy"])
        dec.apply_transform(matrix)
        result, warnings = merge(model, dec, params["style"])

        # Результат — новая загрузка: своя папка, meta.json, событие воронки.
        new_id = uuid.uuid4().hex
        folder = upload_dir(new_id)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "model.stl").write_bytes(result.export(file_type="stl"))
        info = inspect_file(folder / "model.stl", settings.print_bed)
        logo_name = (meta.get("logo") or {}).get("name", "")
        new_meta = {
            "id": new_id,
            "original_name": build_result_name(meta.get("original_name", "model.stl"), params),
            "ext": "stl",
            "size_bytes": (folder / "model.stl").stat().st_size,
            "created_at": _now(),
            "units": "mm",
            "mesh": info.to_dict(),
            "source": "emboss",
            # Откуда модель и что на неё нанесли — видно на странице загрузки.
            "emboss": {
                "parent_id": upload_id,
                "parent_name": meta.get("original_name", ""),
                "job_id": job_id,
                "params": params,
                "summary": describe(params, logo_name),
                "warnings": warnings,
            },
        }
        # Материал из каталога/редактора наследуем — калькулятор подставит его по умолчанию.
        for key in ("catalog", "editor"):
            if meta.get(key):
                new_meta["emboss"]["material"] = meta[key].get("material")
        _save_meta(folder, new_meta)
        track(
            "upload",
            upload_id=new_id,
            props={
                "ext": "stl",
                "size_bytes": new_meta["size_bytes"],
                "watertight": info.watertight,
                "warnings": info.warnings,
                "source": "emboss",
                "parent_upload_id": upload_id,
                "job_id": job_id,
                "kind": params["kind"],
                "style": params["style"],
            },
        )
        record.update(status="done", error=None, warnings=warnings, result_upload_id=new_id)
    except (OpenScadError, EmbossError, MeshError, OSError, ValueError) as e:
        record.update(status="error", error=str(e))
    except HTTPException as e:
        record.update(status="error", error=str(e.detail))
    record["finished_at"] = _now()
    return save_job(record)


# --- API --------------------------------------------------------------------------------


class EmbossRequest(BaseModel):
    params: dict = {}


async def _enqueue(request: Request, upload_id: str, job_id: str) -> None:
    from arq import create_pool

    from app.worker import redis_settings

    pool = getattr(request.app.state, "arq_pool", None)
    if pool is None:
        pool = await create_pool(redis_settings())
        request.app.state.arq_pool = pool
    await pool.enqueue_job(
        "emboss_upload", upload_id, job_id, _job_id=f"emboss:{upload_id}:{job_id}"
    )


@router.get("/api/v1/emboss/options")
def emboss_options() -> dict:
    """Границы и варианты для формы на сайте — чтобы не дублировать числа в двух местах."""
    return {
        "defaults": DEFAULTS,
        "faces": [{"value": f, "label": FACE_LABELS[f]} for f in FACES],
        "fonts": [{"value": f, "label": FONT_LABELS[f]} for f in FONTS],
        "text_maxlen": TEXT_MAXLEN,
        "size_mm": {"min": SIZE_MIN, "max": SIZE_MAX},
        "depth_mm": {"min": DEPTH_MIN, "max": DEPTH_MAX},
        "shift_max": SHIFT_MAX,
        "logo_max_bytes": MAX_LOGO_BYTES,
    }


@router.post("/api/v1/uploads/{upload_id}/embosses", status_code=202)
async def create_emboss(upload_id: str, body: EmbossRequest, request: Request) -> dict:
    meta = load_meta(upload_id)
    params, errors = validate_params(body.params, has_logo=logo_path(upload_id).is_file())
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    job_id = job_id_for(upload_id, meta, params)
    record = load_job(upload_id, job_id)
    cached = record is not None and record["status"] in ("queued", "running", "done")
    await run_in_threadpool(
        track,
        "emboss_build",
        upload_id=upload_id,
        props={"job_id": job_id, "cached": cached, "params": params},
    )
    if cached:
        return record

    record = save_job(new_job(upload_id, job_id, params))
    if settings.redis_url:
        await _enqueue(request, upload_id, job_id)
        return record
    # Без очереди — строим здесь же (разработка и тесты; в проде OpenSCAD есть только в worker).
    return await run_in_threadpool(run_emboss, upload_id, job_id)


@router.get("/api/v1/uploads/{upload_id}/embosses/{job_id}")
def get_emboss(upload_id: str, job_id: str) -> dict:
    load_meta(upload_id)
    record = load_job(upload_id, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    return record
