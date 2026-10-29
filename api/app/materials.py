"""Справочник материалов (B44): config/materials.yaml.

Что здесь:
- `load_materials()` — читает yaml, проверяет поля, возвращает словарь «ключ → описание».
- `sliceable()` — материалы, которые считает слайсер (FDM, включённые, с профилем
  profiles/filament/<КЛЮЧ>.ini). Их принимают /slice и /quote.
- `on_request()` — смолы (SLA): на сайте их можно выбрать, но цену называет владелец —
  клиент оставляет заявку (POST /api/v1/uploads/{id}/request), без оплаты.
- `fits()` — влезает ли модель в область печати этого материала (с поворотом).
- `size_problem()` — то же для сайта: текст клиенту, если деталь больше области печати
  материала (проверяется до постановки расчёта в очередь, см. slices.py).

Файл перечитывается, когда меняется его дата — после правки yaml перезапуск api не нужен.
Если файла нет (например, папку config не смонтировали), слайсер всё равно работает:
материалы берутся по именам профилей в profiles/filament/.
"""

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from app.config import settings

log = logging.getLogger(__name__)

TECHS = ("FDM", "SLA")


class MaterialsError(ValueError):
    """Ошибка в materials.yaml — текст для владельца."""


@dataclass(frozen=True)
class Material:
    key: str  # PLA, PETG-CF, RESIN — как в pricing.yaml и имени профиля
    tech: str  # FDM | SLA
    name: str  # для клиента: «PA (нейлон)»
    tagline: str = ""
    hint: str = ""
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    uses: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    heat_c: int | None = None
    needs_enclosure: bool = False
    max_mm: tuple[float, float, float] | None = None
    enabled: bool = True

    @property
    def on_request(self) -> bool:
        """Цена по запросу: смолы (SLA) слайсер и формула цены не считают."""
        return self.tech == "SLA"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["max_mm"] = list(self.max_mm) if self.max_mm else None
        d["on_request"] = self.on_request
        return d


def _str_list(value, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MaterialsError(f"materials.yaml: {where} — нужен список в квадратных скобках")
    return [str(v) for v in value]


def parse_materials(raw: dict) -> dict[str, Material]:
    """Проверяет содержимое yaml. Ошибка → MaterialsError с подсказкой, где именно."""
    if not isinstance(raw, dict) or not isinstance(raw.get("materials"), dict):
        raise MaterialsError("materials.yaml: нужен раздел materials: со списком материалов")
    out: dict[str, Material] = {}
    for key, m in raw["materials"].items():
        key = str(key).upper()
        where = f"materials.{key}"
        if not isinstance(m, dict):
            raise MaterialsError(f"materials.yaml: {where} — ожидались поля tech, name, ...")
        tech = str(m.get("tech", "")).upper()
        if tech not in TECHS:
            raise MaterialsError(f"materials.yaml: {where}.tech — {' или '.join(TECHS)}")
        max_mm = m.get("max_mm")
        if max_mm is not None:
            try:
                x, y, z = (float(v) for v in max_mm)
            except (TypeError, ValueError) as e:
                raise MaterialsError(
                    f"materials.yaml: {where}.max_mm — три числа, например [256, 256, 256]"
                ) from e
            max_mm = (x, y, z)
        heat = m.get("heat_c")
        out[key] = Material(
            key=key,
            tech=tech,
            name=str(m.get("name") or key),
            tagline=str(m.get("tagline") or ""),
            hint=str(m.get("hint") or ""),
            pros=_str_list(m.get("pros"), f"{where}.pros"),
            cons=_str_list(m.get("cons"), f"{where}.cons"),
            uses=_str_list(m.get("uses"), f"{where}.uses"),
            colors=_str_list(m.get("colors"), f"{where}.colors"),
            heat_c=int(heat) if heat is not None else None,
            needs_enclosure=bool(m.get("needs_enclosure", False)),
            max_mm=max_mm,
            enabled=bool(m.get("enabled", True)),
        )
    return out


_cache: dict = {"path": None, "mtime": None, "data": None}


def _from_profiles() -> dict[str, Material]:
    """Запасной вариант без yaml: FDM-материал на каждый profiles/filament/*.ini."""
    folder = settings.profiles_dir / "filament"
    keys = sorted(p.stem.upper() for p in folder.glob("*.ini")) if folder.is_dir() else []
    return {k: Material(key=k, tech="FDM", name=k) for k in keys}


def load_materials(path: Path | None = None) -> dict[str, Material]:
    """Все материалы из yaml (включая выключенные), в порядке файла."""
    path = Path(path or settings.materials_path)
    if not path.is_file():
        log.warning("Нет %s — материалы берём по профилям слайсера", path)
        return _from_profiles()
    mtime = path.stat().st_mtime
    if _cache["path"] == str(path) and _cache["mtime"] == mtime:
        return _cache["data"]
    data = parse_materials(yaml.safe_load(path.read_text("utf-8")))
    _cache.update(path=str(path), mtime=mtime, data=data)
    return data


def enabled() -> list[Material]:
    """Материалы для сайта: включённые, сначала FDM (в порядке файла), потом смолы."""
    items = [m for m in load_materials().values() if m.enabled]
    return [m for m in items if not m.on_request] + [m for m in items if m.on_request]


def sliceable() -> tuple[str, ...]:
    """Ключи материалов, которые считает слайсер: FDM, включённые.
    Профиль profiles/filament/<КЛЮЧ>.ini у каждого обязателен — это проверяет тест
    (а без профиля слайсер ответит понятной ошибкой «Нет профиля слайсера»)."""
    return tuple(m.key for m in enabled() if not m.on_request)


def on_request() -> tuple[str, ...]:
    """Ключи материалов «цена по запросу» (смолы)."""
    return tuple(m.key for m in enabled() if m.on_request)


def get(key: str) -> Material | None:
    return load_materials().get(str(key).upper())


def fits(size_mm: tuple[float, float, float], area_mm: tuple[float, float, float]) -> bool:
    """Влезает ли деталь в область печати, если её можно повернуть.
    Сравниваем размеры по возрастанию: самый маленький с самым маленьким и т. д."""
    return all(s <= a for s, a in zip(sorted(size_mm), sorted(area_mm), strict=True))


def model_size_mm(meta: dict) -> tuple[float, float, float] | None:
    """Габариты загрузки X×Y×Z, мм, из meta.json (поле mesh.bbox_mm). Нет данных → None."""
    bbox = (meta.get("mesh") or {}).get("bbox_mm") or {}
    try:
        size = tuple(float(bbox.get(k, 0)) for k in ("x", "y", "z"))
    except (TypeError, ValueError):
        return None
    return size if any(size) else None  # type: ignore[return-value]


def size_problem(size_mm: tuple[float, float, float] | None, key: str) -> str | None:
    """Деталь больше области печати материала → понятный текст клиенту, иначе None.

    Область — `max_mm` из config/materials.yaml (по принтерам из docs/PRINTERS.md).
    Без размеров или без `max_mm` проверять нечего — пропускаем."""
    material = get(key)
    if size_mm is None or material is None or not material.max_mm:
        return None
    if fits(size_mm, material.max_mm):
        return None
    dims = " × ".join(f"{v:g}" for v in size_mm)
    area = " × ".join(f"{v:g}" for v in material.max_mm)
    name = material.name or material.key
    return (
        f"Модель {dims} мм не помещается в принтер для {name} (до {area} мм). "
        "Уменьшите масштаб в файле, выберите другой материал или напишите нам — "
        "напечатаем частями и склеим."
    )
