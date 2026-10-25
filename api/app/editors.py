"""Параметрические редакторы (B21): схема параметров → форма → OpenSCAD → STL → заказ.

Источник — папка EDITORS_DIR (по умолчанию `editors/` в корне репо), по подпапке на редактор:
    editors/<slug>/editor.yaml   — название, описание, материал по умолчанию, параметры
                                   (формат описан в editors/spacer/editor.yaml)
    editors/<slug>/model.scad    — сама модель на OpenSCAD; параметры — переменные в начале файла

GET  /api/v1/editors                              — список редакторов со схемами параметров
                                                    (из них сайт рисует формы).
GET  /api/v1/editors/{slug}                       — один редактор.
POST /api/v1/editors/{slug}/builds                — тело {"params": {...}}: проверяем параметры по
                                                    схеме (422 с ошибками по полям), строим STL.
                                                    Одинаковые параметры → одна и та же сборка,
                                                    второй раз не строим. Ставим в очередь (worker)
                                                    или, без REDIS_URL, строим сразу.
GET  /api/v1/editors/{slug}/builds/{id}           — запись сборки: status queued|running|done|error,
                                                    mesh (габариты, объём) после done.
GET  /api/v1/editors/{slug}/builds/{id}/file      — STL для 3D-просмотра в браузере.
POST /api/v1/editors/{slug}/builds/{id}/upload    — «Заказать»: копируем STL в обычную загрузку
                                                    (как у каталога, B20) — дальше /upload/<id>,
                                                    расчёт печати, цена, заказ.

Сборки лежат в DATA_DIR/editors/<slug>/<id>/ (model.stl + build.json); id — хэш от slug,
даты scad-файла и параметров. Старые сборки чистит ночная уборка (app/cleanup.py).
Схемы перечитываются, когда меняется дата editor.yaml, — перезапуск не нужен.
"""

import hashlib
import json
import math
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import jobs
from app.config import settings
from app.events import track
from app.meshcheck import MeshError, inspect_file
from app.openscad import OpenScadError, run_openscad
from app.uploads import _save_meta, upload_dir

router = APIRouter(prefix="/api/v1/editors", tags=["editors"])

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # имя папки редактора и адрес страницы
NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")  # имя параметра = имя переменной в scad
BUILD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
PARAM_TYPES = ("number", "bool", "choice", "text")
TEXT_MAXLEN = 200  # потолок для текстовых параметров, даже если в yaml написано больше
# Правило проверки двух параметров: «inner_d < outer_d», «height >= 2», «a <= b».
CHECK_RE = re.compile(
    r"^\s*([a-z_][a-z0-9_]*)\s*(<=|>=|<|>)\s*([a-z_][a-z0-9_]*|-?\d+(?:\.\d+)?)\s*$"
)


class EditorError(ValueError):
    """Ошибка в editor.yaml — текст для владельца."""


@dataclass(frozen=True)
class Param:
    name: str  # имя переменной в scad и ключ в params
    label: str  # подпись в форме
    type: str  # number | bool | choice | text
    default: object
    hint: str = ""  # подсказка под полем
    unit: str = ""  # «мм», «шт» — показывается после числа
    min: float | None = None  # только number
    max: float | None = None
    step: float | None = None  # шаг стрелок в форме; число округляется до знаков шага
    integer: bool = False  # number: только целые
    options: tuple[tuple[str, str], ...] = ()  # choice: (значение, подпись)
    maxlen: int = 40  # text


@dataclass(frozen=True)
class Check:
    rule: str  # «inner_d < outer_d»
    message: str  # текст ошибки клиенту


@dataclass(frozen=True)
class Editor:
    slug: str
    title: str
    text: str = ""
    material: str = "PLA"  # материал, выбранный в калькуляторе по умолчанию
    scad: str = "model.scad"  # имя scad-файла в папке редактора
    order: int = 100  # порядок в списке (меньше — выше)
    params: tuple[Param, ...] = ()
    checks: tuple[Check, ...] = field(default_factory=tuple)

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)

    def defaults(self) -> dict:
        return {p.name: p.default for p in self.params}


# --- чтение editor.yaml -----------------------------------------------------------------


def editors_dir() -> Path:
    return settings.editors_dir


def editor_dir(slug: str) -> Path:
    return editors_dir() / slug


def _num(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise EditorError(f"editor.yaml: у {where} ожидалось число, а не «{value}»")
    return float(value)


def _parse_param(item: dict, slug: str) -> Param:
    if not isinstance(item, dict):
        raise EditorError(
            f"editor.yaml ({slug}): параметр должен быть словарём с полями name, type"
        )
    name = str(item.get("name") or "").strip()
    if not NAME_RE.match(name):
        raise EditorError(
            f"editor.yaml ({slug}): имя параметра «{name}» — только a-z, 0-9 и «_», "
            "начинается с буквы"
        )
    where = f"параметра {name}"
    ptype = str(item.get("type") or "number").strip()
    if ptype not in PARAM_TYPES:
        raise EditorError(f"editor.yaml ({slug}): у {where} тип должен быть из {PARAM_TYPES}")
    label = str(item.get("label") or name).strip()
    common = {
        "name": name,
        "label": label,
        "type": ptype,
        "hint": str(item.get("hint") or "").strip(),
        "unit": str(item.get("unit") or "").strip(),
    }

    if ptype == "number":
        lo = _num(item["min"], where) if "min" in item else None
        hi = _num(item["max"], where) if "max" in item else None
        step = _num(item["step"], where) if "step" in item else None
        integer = bool(item.get("integer", False))
        if lo is not None and hi is not None and lo > hi:
            raise EditorError(f"editor.yaml ({slug}): у {where} min больше max")
        if step is not None and step <= 0:
            raise EditorError(f"editor.yaml ({slug}): у {where} step должен быть больше нуля")
        default = _num(item.get("default", lo if lo is not None else 0), where)
        if integer:
            default = int(default)
        param = Param(default=default, min=lo, max=hi, step=step, integer=integer, **common)
    elif ptype == "bool":
        param = Param(default=bool(item.get("default", False)), **common)
    elif ptype == "choice":
        options: list[tuple[str, str]] = []
        for opt in item.get("options") or []:
            if isinstance(opt, dict):
                value, text = str(opt.get("value", "")).strip(), str(opt.get("label", "")).strip()
            else:
                value, text = str(opt).strip(), str(opt).strip()
            if not value:
                raise EditorError(f"editor.yaml ({slug}): у {where} пустой вариант в options")
            options.append((value, text or value))
        if not options:
            raise EditorError(f"editor.yaml ({slug}): у {where} нет вариантов options")
        default = str(item.get("default", options[0][0])).strip()
        if default not in {v for v, _ in options}:
            raise EditorError(f"editor.yaml ({slug}): у {where} default не из options")
        param = Param(default=default, options=tuple(options), **common)
    else:  # text
        maxlen = int(item.get("maxlen", 40))
        if not 1 <= maxlen <= TEXT_MAXLEN:
            raise EditorError(f"editor.yaml ({slug}): у {where} maxlen от 1 до {TEXT_MAXLEN}")
        default = str(item.get("default", ""))
        if len(default) > maxlen:
            raise EditorError(f"editor.yaml ({slug}): у {where} default длиннее maxlen")
        param = Param(default=default, maxlen=maxlen, **common)

    # Значение по умолчанию само должно проходить проверку — иначе форма откроется с ошибкой.
    error = validate_value(param, param.default)
    if error:
        raise EditorError(f"editor.yaml ({slug}): default у {where} не проходит проверку: {error}")
    return param


def parse_editor(slug: str, raw: dict) -> Editor:
    """Проверяет editor.yaml. Про наличие scad-файла — отдельно, при сборке."""
    if not SLUG_RE.match(slug):
        raise EditorError(f"Имя папки редактора «{slug}» — только a-z, 0-9 и дефис")
    if not isinstance(raw, dict):
        raise EditorError(f"editor.yaml ({slug}): ожидались поля title, params")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise EditorError(f"editor.yaml ({slug}): не заполнено поле «title»")

    params: list[Param] = []
    for item in raw.get("params") or []:
        param = _parse_param(item, slug)
        if any(p.name == param.name for p in params):
            raise EditorError(f"editor.yaml ({slug}): параметр «{param.name}» встречается дважды")
        params.append(param)
    if not params:
        raise EditorError(f"editor.yaml ({slug}): нет ни одного параметра")

    names = {p.name for p in params if p.type == "number"}
    checks: list[Check] = []
    for item in raw.get("checks") or []:
        rule = str((item or {}).get("rule") or "").strip() if isinstance(item, dict) else str(item)
        m = CHECK_RE.match(rule)
        if not m:
            raise EditorError(
                f"editor.yaml ({slug}): правило «{rule}» — нужно вида «inner_d < outer_d» или "
                "«height >= 2»"
            )
        left, _, right = m.groups()
        if left not in names or (not _is_number(right) and right not in names):
            raise EditorError(
                f"editor.yaml ({slug}): в правиле «{rule}» есть неизвестный числовой параметр"
            )
        message = str(item.get("message") or "").strip() if isinstance(item, dict) else ""
        checks.append(Check(rule=rule, message=message or f"Нужно, чтобы {rule}"))

    scad = Path(str(raw.get("scad") or "model.scad")).name
    if not scad.endswith(".scad"):
        raise EditorError(f"editor.yaml ({slug}): файл модели должен быть .scad")
    return Editor(
        slug=slug,
        title=title,
        text=str(raw.get("text") or "").strip(),
        material=str(raw.get("material") or "PLA").strip().upper(),
        scad=scad,
        order=int(raw.get("order", 100)),
        params=tuple(params),
        checks=tuple(checks),
    )


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


@lru_cache(maxsize=64)
def _load_cached(slug: str, path: str, mtime_ns: int) -> Editor:
    raw = yaml.safe_load(Path(path).read_text("utf-8"))
    return parse_editor(slug, raw)


def load_editor(slug: str) -> Editor | None:
    """Один редактор по имени папки; нет папки или yaml — None. Сломанный yaml — EditorError."""
    if not SLUG_RE.match(slug):
        return None
    path = editor_dir(slug) / "editor.yaml"
    if not path.is_file():
        return None
    return _load_cached(slug, str(path.resolve()), path.stat().st_mtime_ns)


def load_editors() -> list[Editor]:
    """Все редакторы, отсортированные по order, потом по slug."""
    root = editors_dir()
    if not root.is_dir():
        return []
    editors = []
    for folder in sorted(root.iterdir()):
        if folder.is_dir() and SLUG_RE.match(folder.name):
            editor = load_editor(folder.name)
            if editor is not None:
                editors.append(editor)
    return sorted(editors, key=lambda e: (e.order, e.slug))


def scad_path(editor: Editor) -> Path:
    return editor_dir(editor.slug) / editor.scad


# --- проверка параметров ----------------------------------------------------------------


def _round_to_step(value: float, step: float | None) -> float:
    """Округляем до знаков шага: шаг 0.5 → 1 знак, 0.01 → 2 знака, 1 → целое; без шага — 3."""
    if step is None:
        return round(value, 3)
    exponent = Decimal(str(step)).normalize().as_tuple().exponent
    decimals = max(0, -int(exponent)) if isinstance(exponent, int) else 3
    return round(value, min(decimals, 6))


def validate_value(param: Param, value: object) -> str | None:
    """Проверяет одно значение по схеме. Возвращает текст ошибки или None."""
    if param.type == "number":
        if isinstance(value, bool):
            return "Нужно число."
        if isinstance(value, str):
            try:
                value = float(value.replace(",", ".").strip())
            except ValueError:
                return "Нужно число."
        if not isinstance(value, int | float) or not math.isfinite(value):
            return "Нужно число."
        if param.integer and float(value) != int(value):
            return "Нужно целое число."
        if param.min is not None and value < param.min:
            return f"Не меньше {param.min:g}{' ' + param.unit if param.unit else ''}."
        if param.max is not None and value > param.max:
            return f"Не больше {param.max:g}{' ' + param.unit if param.unit else ''}."
        return None
    if param.type == "bool":
        if isinstance(value, bool) or value in ("true", "false", 0, 1):
            return None
        return "Нужно да или нет."
    if param.type == "choice":
        if str(value) not in {v for v, _ in param.options}:
            return "Выберите один из вариантов."
        return None
    # text
    if not isinstance(value, str):
        return "Нужен текст."
    text = value.strip()
    if len(text) > param.maxlen:
        return f"Не длиннее {param.maxlen} символов."
    if any(ord(ch) < 32 for ch in text):
        return "Текст без переносов строк и служебных символов."
    return None


def clean_value(param: Param, value: object) -> object:
    """Приводит проверенное значение к типу, который уйдёт в OpenSCAD и в запись сборки."""
    if param.type == "number":
        if isinstance(value, str):
            value = float(value.replace(",", ".").strip())
        if param.integer:
            return int(value)
        num = _round_to_step(float(value), param.step)
        return int(num) if num == int(num) else num
    if param.type == "bool":
        return value if isinstance(value, bool) else value in ("true", 1)
    if param.type == "choice":
        return str(value)
    return str(value).strip()


def _check_holds(check: Check, values: dict) -> bool:
    m = CHECK_RE.match(check.rule)
    assert m is not None  # правило проверено при чтении yaml
    left, op, right = m.groups()
    a = float(values[left])
    b = float(right) if _is_number(right) else float(values[right])
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def validate_params(editor: Editor, values: dict | None) -> tuple[dict, dict[str, str]]:
    """Проверяет параметры клиента по схеме.

    Возвращает (чистые параметры — все, с подстановкой умолчаний; ошибки по именам полей).
    Неизвестные имена — тоже ошибка: в scad их нет, значит это опечатка или подделка запроса.
    """
    values = values or {}
    if not isinstance(values, dict):
        return {}, {"params": "Ожидался словарь параметров."}
    clean: dict = {}
    errors: dict[str, str] = {}
    for name in values:
        if editor.param(str(name)) is None:
            errors[str(name)] = "Неизвестный параметр."
    for param in editor.params:
        raw = values.get(param.name, param.default)
        error = validate_value(param, raw)
        if error:
            errors[param.name] = error
        else:
            clean[param.name] = clean_value(param, raw)
    if not errors:
        for check in editor.checks:
            if not _check_holds(check, clean):
                # Ошибку вешаем на левый параметр правила — там её увидят в форме.
                left = CHECK_RE.match(check.rule).group(1)  # type: ignore[union-attr]
                errors.setdefault(left, check.message)
    return clean, errors


# --- сборки -----------------------------------------------------------------------------


def builds_root(slug: str) -> Path:
    return settings.data_dir / "editors" / slug


def build_dir(slug: str, build_id: str) -> Path:
    if not BUILD_ID_RE.match(build_id):
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    return builds_root(slug) / build_id


def build_id_for(editor: Editor, params: dict) -> str:
    """Один и тот же редактор, scad-файл и параметры → один id: повторно не строим.
    В хэше есть дата scad-файла: владелец поправил модель — старые сборки не подойдут."""
    path = scad_path(editor)
    mtime = path.stat().st_mtime_ns if path.is_file() else 0
    key = json.dumps([editor.slug, mtime, params], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record_path(slug: str, build_id: str) -> Path:
    return build_dir(slug, build_id) / "build.json"


def stl_path(slug: str, build_id: str) -> Path:
    return build_dir(slug, build_id) / "model.stl"


def load_build(slug: str, build_id: str) -> dict | None:
    path = record_path(slug, build_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text("utf-8"))


def save_build(record: dict) -> dict:
    path = record_path(record["editor"], record["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


def new_build(editor: Editor, params: dict) -> dict:
    build_id = build_id_for(editor, params)
    return {
        "id": build_id,
        "editor": editor.slug,
        "params": params,
        "status": "queued",
        "attempt": 0,  # номер попытки; растёт, если прежняя задача была брошена (app/jobs.py)
        "created_at": _now(),
        "started_at": None,  # когда worker взял задачу
        "finished_at": None,
        "error": None,
        "mesh": None,  # MeshInfo.to_dict() после сборки
        "file_url": f"/api/v1/editors/{editor.slug}/builds/{build_id}/file",
    }


def run_build(slug: str, build_id: str) -> dict:
    """Сама работа (в worker или прямо в API без очереди): OpenSCAD → STL → габариты."""
    record = load_build(slug, build_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    record.update(status="running", started_at=_now())
    save_build(record)
    try:
        editor = load_editor(slug)
        if editor is None:
            raise EditorError(f"Редактор «{slug}» не найден.")
        out = stl_path(slug, build_id)
        run_openscad(scad_path(editor), out, record["params"])
        info = inspect_file(out, settings.print_bed)
        record.update(status="done", mesh=info.to_dict(), error=None)
    except (OpenScadError, EditorError, MeshError, OSError, yaml.YAMLError) as e:
        record.update(status="error", error=str(e))
    record["finished_at"] = _now()
    return save_build(record)


def _fmt(value: float) -> str:
    """12.5 → «12,5», 20.0 → «20»."""
    return f"{value:g}".replace(".", ",")


def describe_params(editor: Editor, params: dict) -> str:
    """Параметры словами для страницы загрузки и админки:
    «Внешний диаметр 20 мм, Форма: Круглая, Фаска по краям: да»."""
    parts = []
    for p in editor.params:
        if p.name not in params:
            continue
        v = params[p.name]
        if p.type == "number":
            parts.append(f"{p.label} {_fmt(float(v))}{' ' + p.unit if p.unit else ''}")
        elif p.type == "bool":
            parts.append(f"{p.label}: {'да' if v else 'нет'}")
        elif p.type == "choice":
            parts.append(f"{p.label}: {dict(p.options).get(str(v), v)}")
        elif str(v).strip():
            parts.append(f"{p.label}: «{str(v).strip()}»")
    return ", ".join(parts)


# --- ответы API -------------------------------------------------------------------------


def editor_card(editor: Editor) -> dict:
    """Схема для сайта: по ней рисуется форма."""
    card = asdict(editor)
    card["params"] = [
        {**asdict(p), "options": [{"value": v, "label": t} for v, t in p.options]}
        for p in editor.params
    ]
    card["checks"] = [asdict(c) for c in editor.checks]
    card["scad_ready"] = scad_path(editor).is_file()
    return card


def _editor_or_404(slug: str) -> Editor:
    try:
        editor = load_editor(slug)
    except (EditorError, yaml.YAMLError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if editor is None:
        raise HTTPException(status_code=404, detail="Редактор не найден.")
    return editor


def _build_or_404(slug: str, build_id: str) -> dict:
    record = jobs.settle(load_build(slug, build_id), save_build)  # брошенная → error
    if record is None:
        raise HTTPException(status_code=404, detail="Сборка не найдена.")
    return record


class BuildRequest(BaseModel):
    params: dict = {}


@router.get("")
def get_editors() -> dict:
    try:
        editors = load_editors()
    except (EditorError, yaml.YAMLError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"editors": [editor_card(e) for e in editors]}


@router.get("/{slug}")
def get_editor(slug: str) -> dict:
    return editor_card(_editor_or_404(slug))


async def _enqueue(request: Request, slug: str, build_id: str, attempt: int = 0) -> None:
    """Кладёт задачу в arq (общий пул — app/jobs.py). attempt > 0 — повтор после брошенной
    сборки, id задачи другой (см. jobs.retry_job_id)."""
    job_id = jobs.retry_job_id(f"editor:{slug}:{build_id}", attempt)
    await jobs.enqueue(request, "build_editor", slug, build_id, job_id=job_id)


@router.post("/{slug}/builds", status_code=202)
async def create_build(slug: str, body: BuildRequest, request: Request) -> dict:
    editor = _editor_or_404(slug)
    params, errors = validate_params(editor, body.params)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    build_id = build_id_for(editor, params)
    record = jobs.settle(load_build(slug, build_id), save_build)  # брошенная → error
    cached = record is not None and record["status"] in ("queued", "running", "done")
    await run_in_threadpool(
        track,
        "editor_build",
        props={"editor_slug": slug, "build_id": build_id, "cached": cached, "params": params},
    )
    if cached:
        return record  # уже строим или уже построили

    attempt = jobs.next_attempt(record)  # была ошибка/брошена → повтор под новым id задачи
    record = new_build(editor, params)
    record["attempt"] = attempt
    save_build(record)
    if settings.redis_url:
        try:
            await _enqueue(request, slug, build_id, attempt)
        except jobs.QueueUnavailable:
            # В очередь не попало — записи быть не должно, иначе клиент ждал бы её вечно.
            record_path(slug, build_id).unlink(missing_ok=True)
            raise jobs.queue_unavailable() from None
        return record
    # Без очереди — строим здесь же (разработка и тесты; в проде OpenSCAD есть только в worker).
    return await run_in_threadpool(run_build, slug, build_id)


@router.get("/{slug}/builds/{build_id}")
def get_build(slug: str, build_id: str) -> dict:
    _editor_or_404(slug)
    return _build_or_404(slug, build_id)


@router.get("/{slug}/builds/{build_id}/file")
def get_build_file(slug: str, build_id: str) -> FileResponse:
    editor = _editor_or_404(slug)
    record = _build_or_404(slug, build_id)
    path = stl_path(slug, build_id)
    if record["status"] != "done" or not path.is_file():
        raise HTTPException(status_code=404, detail="Модель ещё не построена.")
    return FileResponse(path, media_type="application/octet-stream", filename=f"{editor.slug}.stl")


@router.post("/{slug}/builds/{build_id}/upload", status_code=201)
async def upload_from_build(slug: str, build_id: str) -> dict:
    """Кнопка «Заказать»: копируем построенный STL в обычную загрузку (как каталог, B20).

    У заказа остаётся своя копия файла: сборки чистятся ночной уборкой, а владелец может
    поменять scad-файл — клиент получит ровно то, что видел.
    """
    editor = _editor_or_404(slug)
    record = _build_or_404(slug, build_id)
    src = stl_path(slug, build_id)
    if record["status"] != "done" or not src.is_file():
        raise HTTPException(status_code=409, detail="Модель ещё не построена.")

    upload_id = uuid.uuid4().hex
    folder = upload_dir(upload_id)
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(src, folder / "model.stl")
    mesh = (
        record["mesh"] or (await run_in_threadpool(inspect_file, src, settings.print_bed)).to_dict()
    )
    meta = {
        "id": upload_id,
        "original_name": f"{editor.title}.stl",
        "ext": "stl",
        "size_bytes": src.stat().st_size,
        "created_at": _now(),
        "units": "mm",
        "mesh": mesh,
        # Откуда взялась загрузка — видно в meta.json и в событиях воронки.
        "source": "editor",
        "editor": {
            "slug": editor.slug,
            "title": editor.title,
            "material": editor.material,
            "build_id": build_id,
            "params": record["params"],
            "summary": describe_params(editor, record["params"]),
        },
    }
    _save_meta(folder, meta)
    await run_in_threadpool(
        track,
        "upload",
        upload_id=upload_id,
        props={
            "ext": "stl",
            "size_bytes": meta["size_bytes"],
            "watertight": mesh["watertight"],
            "warnings": mesh["warnings"],
            "source": "editor",
            "editor_slug": editor.slug,
            "build_id": build_id,
        },
    )
    return meta


# --- уборка -----------------------------------------------------------------------------


def cleanup_builds(max_age_days: int, now: datetime | None = None, dry_run: bool = False) -> dict:
    """Удаляет сборки старше max_age_days (по build.json; без него — по дате папки).

    Сборка — просмотр, не заказ: у заказа своя копия STL в загрузках. Зовётся из app/cleanup.py.
    0 = не удалять.
    """
    now = now or datetime.now(UTC)
    report = {"checked": 0, "deleted": 0, "freed_bytes": 0}
    root = settings.data_dir / "editors"
    if max_age_days <= 0 or not root.is_dir():
        return report
    for folder in sorted(p for p in root.glob("*/*") if p.is_dir()):
        if not BUILD_ID_RE.match(folder.name):
            continue
        report["checked"] += 1
        created = datetime.fromtimestamp(folder.stat().st_mtime, UTC)
        record_file = folder / "build.json"
        if record_file.is_file():
            try:
                created = datetime.fromisoformat(
                    json.loads(record_file.read_text("utf-8"))["created_at"]
                )
            except (ValueError, KeyError, json.JSONDecodeError):
                pass
        if (now - created).days < max_age_days:
            continue
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        if not dry_run:
            shutil.rmtree(folder, ignore_errors=True)
        report["deleted"] += 1
        report["freed_bytes"] += size
    return report


def reload_editors() -> None:
    """Сброс кэша — для тестов."""
    _load_cached.cache_clear()
