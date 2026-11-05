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
GET    /api/v1/uploads/{id}/logo              — сам SVG (редактор B62 рисует его на модели).
DELETE /api/v1/uploads/{id}/logo              — убрать логотип.
POST   /api/v1/uploads/{id}/embosses          — тело {"params": {...}}: проверка параметров
                                                (422 с ошибками по полям), сборка. Размещение из
                                                интерактивного редактора (B60) — params.placement
                                                = {point, normal, up, size_mm, depth_mm, mode};
                                                тогда face/dx/dy не нужны. Одинаковые
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
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from lxml import etree
from pydantic import BaseModel

from app import jobs
from app.config import settings
from app.events import track
from app.limits import uploads_guard
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
    # Размещение из интерактивного редактора (B60, docs/EDITOR.md): точка на поверхности,
    # нормаль наружу и вектор «верх» надписи — всё в мм, в системе модели (Z вверх).
    # Если задано — face/dx/dy не используются. Внутри могут быть size_mm, depth_mm и mode
    # ("raised"|"engraved") — они перекрывают одноимённые параметры выше.
    "placement": None,
}
PLACEMENT_KEYS = ("point", "normal", "up", "size_mm", "depth_mm", "mode")
COORD_MAX = 10_000.0  # мм: координаты точки размещения по модулю
# B64: точка размещения должна лежать на поверхности модели с таким допуском (мм) — запас
# overlap в emboss.scad 0,3 мм плюс погрешность округления и «толщина» грубой сетки клиента.
CONTACT_TOL_MM = 1.0
# B64a: изогнутая поверхность — нормали треугольников в радиусе размера надписи вокруг точки
# расходятся с нормалью в точке больше чем на столько градусов. Тогда запас overlap в
# emboss.scad поднимаем до глубины надписи, чтобы края букв не повисли над поверхностью.
CURVED_MAX_DEG = 15.0
OVERLAP_MM = 0.3  # обычный запас (как в emboss.scad)
# Край модели под надписью (BUG QA 05.11): углы и середины сторон прямоугольника надписи
# проецируем лучом на модель. Если под какой-то из этих точек поверхности нет или она ниже
# плоскости надписи больше чем на допуск (CONTACT_TOL_MM + запас overlap) — буквы частично
# висят за краем модели: предупреждение «edge_overhang».
EDGE_FACE_COS = math.cos(math.radians(80))  # грань под ≥ 80° к нормали — край, не изгиб
TEXT_CHAR_WIDTH = 0.62  # ширина буквы ≈ 0,62 размера — та же прикидка, что textWidthMm на сайте
# B65: несколько наложений из редактора — одной сборкой. Первое лежит в params, остальные —
# в params["more"] (каждое со своим размещением), наносятся по порядку списка.
MAX_OVERLAYS = 10


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


@router.get("/api/v1/uploads/{upload_id}/logo")
def get_logo(upload_id: str) -> Response:
    """Отдать SVG-логотип модели — редактор (B62) выдавливает его контуры в окне просмотра.

    Файл проверен при загрузке (check_svg: без скриптов и ссылок), но на всякий случай
    запрещаем браузеру что-либо исполнять, если SVG откроют напрямую по ссылке.
    """
    load_meta(upload_id)  # 404, если модели нет
    path = logo_path(upload_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Логотип не загружен.")
    return Response(
        content=path.read_bytes(),
        media_type="image/svg+xml",
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


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

    placement, perrors = validate_placement(values["placement"])
    if perrors:
        errors.update(perrors)
    else:
        clean["placement"] = placement
        if placement:
            # Размер, глубина и режим из редактора важнее одноимённых полей снаружи.
            for key in ("size_mm", "depth_mm"):
                if key in placement:
                    clean[key] = placement[key]
            if "mode" in placement:
                clean["style"] = placement["mode"]
    return clean, errors


def _vector(value: object) -> list[float] | None:
    """[x, y, z] из трёх конечных чисел (строки «1,5» тоже годятся) или None."""
    if not isinstance(value, list | tuple) or len(value) != 3:
        return None
    out = []
    for v in value:
        num, error = _number(v, -COORD_MAX, COORD_MAX)
        if error:
            return None
        out.append(num)
    return out


def validate_placement(raw: object) -> tuple[dict | None, dict[str, str]]:
    """Размещение из редактора → (чистое; ошибки по полям вида placement.point).

    Нормаль приводится к единичной, «верх» — к единичному и перпендикулярному нормали
    (tangent_frame). Так одинаковое размещение всегда даёт одну и ту же сборку (job_id).
    """
    if raw is None:
        return None, {}
    if not isinstance(raw, dict):
        return None, {"placement": "Ожидался словарь размещения."}
    errors: dict[str, str] = {}
    for name in raw:
        if name not in PLACEMENT_KEYS:
            errors[f"placement.{name}"] = "Неизвестный параметр."
    vectors: dict[str, list[float]] = {}
    for name in ("point", "normal", "up"):
        vec = _vector(raw.get(name))
        if vec is None:
            errors[f"placement.{name}"] = "Нужны три числа [x, y, z] в мм."
        else:
            vectors[name] = vec
    if "normal" in vectors and float(np.linalg.norm(vectors["normal"])) < 1e-9:
        errors["placement.normal"] = "Нормаль не может быть нулевой."
    clean: dict = {}
    for name, lo, hi in (("size_mm", SIZE_MIN, SIZE_MAX), ("depth_mm", DEPTH_MIN, DEPTH_MAX)):
        if name in raw:
            num, error = _number(raw[name], lo, hi)
            if error:
                errors[f"placement.{name}"] = error
            else:
                clean[name] = num
    if "mode" in raw:
        if str(raw["mode"]) not in STYLES:
            errors["placement.mode"] = "Выберите один из вариантов."
        else:
            clean["mode"] = str(raw["mode"])
    if errors:
        return None, errors
    _x, up, normal = tangent_frame(np.array(vectors["normal"]), np.array(vectors["up"]))
    clean["point"] = _round_vec(vectors["point"], 3)
    clean["normal"] = _round_vec(normal, 6)
    clean["up"] = _round_vec(up, 6)
    return clean, {}


def _round_vec(vec, digits: int) -> list[float]:
    """Округление координат; «−0.0» становится «0.0», чтобы одинаковые размещения совпадали
    и в JSON (от этого зависит job_id)."""
    return [round(float(v), digits) + 0.0 for v in vec]


def tangent_frame(normal: np.ndarray, up: np.ndarray | None = None) -> tuple[np.ndarray, ...]:
    """Локальная система тиснения в точке поверхности: (right, up, normal), все единичные.

    normal — наружу от поверхности (станет осью Z фигуры из OpenSCAD, «лицом» наружу);
    up — куда смотрит верх букв; его проекция на касательную плоскость становится осью Y.
    Если up не задан или параллелен нормали — берём мировой Z («верх» модели), а на
    горизонтальной грани — мировой Y (как у face="top"). right = up × normal — так текст
    читается снаружи, а не зеркально. Та же формула — в web/lib/editor/math.ts.
    """
    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    candidates = [up] if up is not None else []
    candidates += [np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0])]
    for hint in candidates:
        h = np.asarray(hint, dtype=float)
        y = h - np.dot(h, n) * n
        length = float(np.linalg.norm(y))
        if length > 1e-6:
            y = y / length
            break
    x = np.cross(y, n)
    return x, y, n


def placement_transform(point, normal, up) -> np.ndarray:
    """Матрица 4×4: фигуру из плоскости XY (лицом вверх, центр в нуле) — в точку поверхности.

    Столбцы — оси локальной системы (tangent_frame), последний — точка. Для грани
    «сверху» в центре и up = +Y совпадает с face_transform(..., "top", 0, 0).
    """
    x, y, z = tangent_frame(np.asarray(normal, dtype=float), np.asarray(up, dtype=float))
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2] = x, y, z
    m[:3, 3] = np.asarray(point, dtype=float)
    return m


def surface_distance(mesh: trimesh.Trimesh, point) -> tuple[float, int]:
    """Расстояние от точки до поверхности сетки и номер ближайшего треугольника.

    Без rtree (его нет в зависимостях): считаем ближайшую точку на КАЖДОМ треугольнике
    разом через numpy (trimesh.triangles.closest_point) — для 500 тыс. треугольников это
    доли секунды и ~40 МБ памяти, зато точно и без индексов.
    """
    p = np.asarray(point, dtype=float)
    tris = mesh.triangles
    if len(tris) == 0:
        return math.inf, -1
    closest = trimesh.triangles.closest_point(tris, np.repeat(p[None, :], len(tris), axis=0))
    dist = np.linalg.norm(closest - p, axis=1)
    i = int(np.argmin(dist))
    return float(dist[i]), i


def surface_spread(mesh: trimesh.Trimesh, point, normal, radius_mm: float) -> float:
    """B64a: насколько изогнута поверхность вокруг точки — наибольший угол (градусы) между
    нормалью в точке и нормалями треугольников, у которых есть точка ближе radius_mm.

    Треугольники, смотрящие «назад» (угол больше 90°), не считаем: это обратная сторона
    тонкой стенки, а не изгиб под надписью; почти перпендикулярные (≥ 80°) — тоже: это
    соседняя грань у края модели. Вырожденные треугольники (нулевая нормаль) —
    тоже пропускаем.
    """
    p = np.asarray(point, dtype=float)
    n = np.asarray(normal, dtype=float)
    tris = mesh.triangles
    if len(tris) == 0:
        return 0.0
    closest = trimesh.triangles.closest_point(tris, np.repeat(p[None, :], len(tris), axis=0))
    near = np.linalg.norm(closest - p, axis=1) <= radius_mm
    normals = mesh.face_normals[near]
    normals = normals[np.linalg.norm(normals, axis=1) > 0.5]
    cos = normals @ n
    # Обратная сторона тонкой стенки (> 90°) — не изгиб. Соседняя грань под прямым углом
    # (≥ 80°) — это край модели, а не изгиб: его ловит edge_overhang.
    cos = cos[cos > EDGE_FACE_COS]
    if len(cos) == 0:
        return 0.0
    return float(np.degrees(np.arccos(np.clip(cos.min(), -1.0, 1.0))))


def check_contact(
    mesh: trimesh.Trimesh, placement: dict, size_mm: float | None = None
) -> tuple[dict, list[str]]:
    """B64: размещение из редактора касается поверхности? Иначе EmbossError (→ 422).

    Точка дальше CONTACT_TOL_MM от сетки — надпись «висит в воздухе» (клиент тянул гизмо за
    край или модель поменяли после размещения). Нормаль, смотрящая внутрь (сетка с
    вывернутыми треугольниками), разворачиваем наружу — выпуклая надпись должна торчать
    наружу, врезанная — уходить внутрь; об этом предупреждение «normal_flipped».
    """
    dist, face = surface_distance(mesh, placement["point"])
    if dist > CONTACT_TOL_MM:
        raise EmbossError(
            f"Надпись не касается поверхности модели (до неё {dist:.1f} мм) — "
            "поставьте её на модель заново."
        )
    warnings: list[str] = []
    face_normal = mesh.face_normals[face]
    if float(np.dot(face_normal, placement["normal"])) < 0:
        x, up, normal = tangent_frame(-np.asarray(placement["normal"]), np.asarray(placement["up"]))
        placement = {**placement, "normal": _round_vec(normal, 6), "up": _round_vec(up, 6)}
        warnings.append("normal_flipped")
    # B64a: изогнутая поверхность под надписью (size_mm — размер надписи/ширина логотипа).
    if size_mm and surface_spread(mesh, placement["point"], placement["normal"], size_mm) > (
        CURVED_MAX_DEG
    ):
        warnings.append("curved_surface")
    return placement, warnings


def ray_hits(mesh: trimesh.Trimesh, origin, direction) -> np.ndarray:
    """Расстояния вдоль луча до всех треугольников, которые он пересекает (по возрастанию).

    Алгоритм Мёллера — Трумбора разом на numpy по всем треугольникам: rtree/embree, которые
    нужны trimesh.ray, в зависимостях нет, а несколько лучей на 500 тыс. треугольников —
    доли секунды.
    """
    o = np.asarray(origin, dtype=float)
    d = np.asarray(direction, dtype=float)
    tris = mesh.triangles
    if len(tris) == 0:
        return np.zeros(0)
    v0 = tris[:, 0]
    e1 = tris[:, 1] - v0
    e2 = tris[:, 2] - v0
    pvec = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, pvec)
    ok = np.abs(det) > 1e-12
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    tvec = o - v0
    u = np.einsum("ij,ij->i", tvec, pvec) * inv
    qvec = np.cross(tvec, e1)
    v = (qvec @ d) * inv
    t = np.einsum("ij,ij->i", e2, qvec) * inv
    eps = 1e-9
    hit = ok & (u >= -eps) & (v >= -eps) & (u + v <= 1 + eps) & (t > 0)
    return np.sort(t[hit])


def _svg_aspect(upload_id: str | None) -> float:
    """Высота / ширина загруженного логотипа (по viewBox или width/height); не вышло — 1."""
    if not upload_id:
        return 1.0
    try:
        root = etree.fromstring(logo_path(upload_id).read_bytes())
    except (OSError, etree.XMLSyntaxError):
        return 1.0
    box = (root.get("viewBox") or "").replace(",", " ").split()
    try:
        if len(box) == 4 and float(box[2]) > 0:
            return float(box[3]) / float(box[2])
        w = float(re.sub(r"[a-z%]+$", "", root.get("width") or ""))
        h = float(re.sub(r"[a-z%]+$", "", root.get("height") or ""))
        return h / w if w > 0 and h > 0 else 1.0
    except ValueError:
        return 1.0


def footprint_mm(params: dict, logo_aspect: float = 1.0) -> tuple[float, float]:
    """Ширина и высота наложения в его плоскости (мм), без поворота angle.

    Надпись — прикидка как у сайта (textWidthMm в web/lib/editor/math.ts): буква ≈ 0,62
    размера, не уже одной буквы-квадрата; высота = размер. Логотип: ширина = size_mm,
    высота — по пропорциям SVG.
    """
    size = float(params["size_mm"])
    if params.get("kind") == "logo":
        return size, size * logo_aspect
    chars = max(1, len((params.get("text") or "").strip()))
    return max(size, chars * size * TEXT_CHAR_WIDTH), size


def edge_overhang(
    mesh: trimesh.Trimesh,
    placement: dict,
    width: float,
    height: float,
    angle_deg: float = 0.0,
    max_gap: float = CONTACT_TOL_MM + OVERLAP_MM,
) -> float:
    """Насколько (мм) прямоугольник надписи «висит» над моделью — 0, если лежит на ней.

    Берём 4 угла и 4 середины сторон прямоугольника в плоскости надписи (касательная
    плоскость в точке размещения) и пускаем из каждой луч внутрь модели (против нормали),
    начиная чуть выше — на высоту надписи. Под точкой нет поверхности — висит на всю высоту
    луча; поверхность ниже плоскости больше чем на max_gap — висит на эту разницу.
    Поверхность выше плоскости (вогнутая) — не страшно: буквы утонут в модели.
    """
    x, y, n = tangent_frame(np.asarray(placement["normal"]), np.asarray(placement["up"]))
    a = math.radians(angle_deg)
    rx = math.cos(a) * x + math.sin(a) * y  # поворот angle в плоскости (как rotate в .scad)
    ry = -math.sin(a) * x + math.cos(a) * y
    p = np.asarray(placement["point"], dtype=float)
    lift = max(width, height)  # начало луча над плоскостью надписи
    worst = 0.0
    for sx, sy in ((-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)):
        sample = p + rx * (sx * width / 2) + ry * (sy * height / 2)
        hits = ray_hits(mesh, sample + n * lift, -n)
        if len(hits) == 0:
            worst = max(worst, lift)
            continue
        gap = float(hits[0]) - lift  # > 0 — поверхность ниже плоскости надписи
        if gap > max_gap:
            worst = max(worst, gap)
    return worst


def _check_one(
    mesh: trimesh.Trimesh, params: dict, upload_id: str | None = None
) -> tuple[dict, list[str]]:
    fixed, warnings = check_contact(mesh, params["placement"], params.get("size_mm"))
    params = {**params, "placement": fixed}
    curved = "curved_surface" in warnings
    if curved:
        # Запас «внутрь модели» = вся глубина: на изгибе края букв отходят от поверхности.
        params["overlap_mm"] = max(OVERLAP_MM, float(params["depth_mm"]))
    if params.get("size_mm"):
        aspect = _svg_aspect(upload_id) if params.get("kind") == "logo" else 1.0
        width, height = footprint_mm(params, aspect)
        # На изогнутой поверхности края и так отходят (об этом curved_surface) — там ловим
        # только «под краем надписи нет модели совсем».
        overlap = params.get("overlap_mm", OVERLAP_MM)
        max_gap = max(width, height) if curved else CONTACT_TOL_MM + overlap
        angle = float(params.get("angle") or 0)
        if edge_overhang(mesh, fixed, width, height, angle, max_gap) > 0:
            warnings.append("edge_overhang")
    return params, warnings


def check_placement(upload_id: str, meta: dict, params: dict) -> tuple[dict, list[str]]:
    """Проверка касания для запроса из редактора (до постановки в очередь).

    Загружает модель клиента целиком — так же, как inspect_file при загрузке; для файлов до
    100 МБ это секунды, зато клиент получает 422 сразу, а не ошибку сборки через минуту.
    Несколько наложений (B65, params["more"]) проверяются на той же загруженной модели;
    ошибка второго и дальше — с номером: «Наложение 2: …».
    """
    if not params.get("placement"):
        return params, []
    model_file = upload_dir(upload_id) / f"model.{meta['ext']}"
    mesh = load_model(model_file, meta.get("units", "mm"))
    params, warnings = _check_one(mesh, params, upload_id)
    more = []
    for i, extra in enumerate(params.get("more") or [], start=2):
        try:
            extra, extra_warnings = _check_one(mesh, extra, upload_id)
        except EmbossError as e:
            raise EmbossError(f"Наложение {i}: {e}") from None
        more.append(extra)
        warnings += [w for w in extra_warnings if w not in warnings]
    if more:
        params["more"] = more
    return params, warnings


def validate_overlays(
    raw_more: object, primary: dict, has_logo: bool
) -> tuple[list[dict], dict[str, str]]:
    """B65: остальные наложения из редактора (поле `more` запроса) → (чистые; ошибки).

    Каждое — те же параметры, что у первого, и обязательно с размещением; первое тоже
    должно быть из редактора. Ошибки — с номером наложения: «more.0.text».
    """
    if raw_more is None or raw_more == []:
        return [], {}
    if not isinstance(raw_more, list):
        return [], {"more": "Ожидался список наложений."}
    if len(raw_more) + 1 > MAX_OVERLAYS:
        return [], {"more": f"Не больше {MAX_OVERLAYS} наложений за одну сборку."}
    if not primary.get("placement"):
        return [], {"more": "Несколько наложений — только из редактора (нужно размещение)."}
    out: list[dict] = []
    errors: dict[str, str] = {}
    for i, raw in enumerate(raw_more):
        clean, errs = validate_params(raw, has_logo)
        if not errs and not clean.get("placement"):
            errs = {"placement": "Нужно размещение на модели."}
        for key, msg in errs.items():
            errors[f"more.{i}.{key}"] = f"Наложение {i + 2}: {msg}"
        out.append(clean)
    return out, errors


def all_overlays(params: dict) -> list[dict]:
    """Все наложения сборки по порядку: первое (сами params) и остальные из params["more"]."""
    first = {k: v for k, v in params.items() if k != "more"}
    return [first, *(params.get("more") or [])]


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
    more = params.get("more") or []
    if more:
        # B65: несколько наложений — описания через «;».
        first = {k: v for k, v in params.items() if k != "more"}
        return "; ".join(describe(p, logo_name) for p in [first, *more])
    parts = [what, f"{how} {_fmt(params['depth_mm'])} мм"]
    placement = params.get("placement")
    if placement:
        p = placement["point"]
        parts.append(
            f"по размещению в редакторе (точка {_fmt(p[0])}, {_fmt(p[1])}, {_fmt(p[2])} мм)"
        )
    else:
        parts.append(FACE_LABELS[params["face"]])
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
            logo.stat().st_mtime_ns
            if any(p["kind"] == "logo" for p in all_overlays(params)) and logo.is_file()
            else 0,
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
        "attempt": 0,  # номер попытки; растёт, если прежняя задача была брошена (app/jobs.py)
        "created_at": _now(),
        "started_at": None,  # когда worker взял задачу
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
        # B64a: на изогнутой поверхности запас больше (см. check_placement)
        "overlap": params.get("overlap_mm", OVERLAP_MM),
    }


def build_result_name(original_name: str, params: dict) -> str:
    """«bracket.stl» + надпись «ТУЦ» → «bracket + ТУЦ.stl»; логотип → «bracket + логотип.stl»."""
    stem = Path(original_name).stem[:120] or "model"
    what = f"«{params['text']}»" if params["kind"] == "text" else "логотип"
    if params.get("more"):
        what += f" и ещё {len(params['more'])}"
    return f"{stem} + {what}.stl"[:200]


def run_emboss(upload_id: str, job_id: str) -> dict:
    """Сама работа (в worker или прямо в API без очереди): OpenSCAD → тиснение → модель."""
    record = load_job(upload_id, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    record.update(status="running", started_at=_now())
    save_job(record)
    params = record["params"]
    try:
        meta = load_meta(upload_id)
        model_file = upload_dir(upload_id) / f"model.{meta['ext']}"
        result = load_model(model_file, meta.get("units", "mm"))
        merge_warnings: list[str] = []
        # B65: наложения по порядку, каждое — на результат предыдущего (врезанное после
        # выпуклого прорежет и его). Обычно наложение одно.
        for i, one in enumerate(all_overlays(params)):
            dec_file = decoration_path(upload_id, job_id if i == 0 else f"{job_id}-{i}")
            run_openscad(SCAD_PATH, dec_file, _scad_params(one, upload_id))
            dec = trimesh.load(dec_file, file_type="stl", force="mesh")
            if not isinstance(dec, trimesh.Trimesh) or dec.is_empty:
                raise EmbossError("Тиснение получилось пустым — проверьте надпись или логотип.")
            placement = one.get("placement")
            if placement:
                # Редактор (B60): точка, нормаль и «верх» в мм в системе модели.
                matrix = placement_transform(
                    placement["point"], placement["normal"], placement["up"]
                )
            else:
                matrix = face_transform(result.bounds, one["face"], one["dx"], one["dy"])
            dec.apply_transform(matrix)
            result, step_warnings = merge(result, dec, one["style"])
            merge_warnings += [w for w in step_warnings if w not in merge_warnings]
        warnings = [
            w for w in record.get("warnings", []) if w != "merged_without_boolean"
        ] + merge_warnings

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
    # B65: остальные наложения из редактора (у каждого своё размещение) — одной сборкой.
    more: list = []


async def _enqueue(request: Request, upload_id: str, job_id: str, attempt: int = 0) -> None:
    """Кладёт задачу в arq (общий пул — app/jobs.py). attempt > 0 — повтор после брошенной
    задачи, id другой (см. jobs.retry_job_id)."""
    arq_id = jobs.retry_job_id(f"emboss:{upload_id}:{job_id}", attempt)
    await jobs.enqueue(request, "emboss_upload", upload_id, job_id, job_id=arq_id)


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


@router.post(
    "/api/v1/uploads/{upload_id}/embosses",
    status_code=202,
    dependencies=[Depends(uploads_guard)],
)
async def create_emboss(upload_id: str, body: EmbossRequest, request: Request) -> dict:
    meta = load_meta(upload_id)
    has_logo = logo_path(upload_id).is_file()
    params, errors = validate_params(body.params, has_logo=has_logo)
    if not errors:
        more, errors = validate_overlays(body.more, params, has_logo)
        if more:
            params["more"] = more
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    try:
        params, contact_warnings = await run_in_threadpool(check_placement, upload_id, meta, params)
    except EmbossError as e:
        raise HTTPException(
            status_code=422, detail={"errors": {"placement.point": str(e)}}
        ) from None

    job_id = job_id_for(upload_id, meta, params)
    record = jobs.settle(load_job(upload_id, job_id), save_job)  # брошенная → error
    cached = record is not None and record["status"] in ("queued", "running", "done")
    await run_in_threadpool(
        track,
        "emboss_build",
        upload_id=upload_id,
        props={"job_id": job_id, "cached": cached, "params": params},
    )
    if cached:
        # Та же сборка уже есть; предупреждение о развороте нормали — только в этом ответе.
        return {**record, "warnings": list(dict.fromkeys([*contact_warnings, *record["warnings"]]))}

    attempt = jobs.next_attempt(record)  # была ошибка/брошена → повтор под новым id задачи
    record = new_job(upload_id, job_id, params)
    record["attempt"] = attempt
    record["warnings"] = contact_warnings  # предупреждения проверки; дополнятся при сборке
    save_job(record)
    if settings.redis_url:
        try:
            await _enqueue(request, upload_id, job_id, attempt)
        except jobs.QueueUnavailable:
            # В очередь не попало — записи быть не должно, иначе клиент ждал бы её вечно.
            job_path(upload_id, job_id).unlink(missing_ok=True)
            raise jobs.queue_unavailable() from None
        return record
    # Без очереди — строим здесь же (разработка и тесты; в проде OpenSCAD есть только в worker).
    return await run_in_threadpool(run_emboss, upload_id, job_id)


@router.get("/api/v1/uploads/{upload_id}/embosses/{job_id}")
def get_emboss(upload_id: str, job_id: str) -> dict:
    load_meta(upload_id)
    record = jobs.settle(load_job(upload_id, job_id), save_job)  # брошенная → error
    if record is None:
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    return record
