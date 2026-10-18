"""Проверка сетки загруженной модели (STL / 3MF) через trimesh.

Что считаем:
- bbox_mm — габариты по осям X, Y, Z (считаем, что файл в миллиметрах; STL единиц не хранит);
- volume_cm3 — объём; нужен для оценки граммов до слайсинга;
- watertight — замкнута ли сетка (нет дыр). Если нет — пробуем закрыть дыры;
- warnings — список кодов предупреждений для клиента и владельца.

Единицы: STL не содержит единиц. Если модель крошечная (≤ 10 мм по самой длинной
стороне), скорее всего она сохранена в дюймах — говорим об этом клиенту (unit_hint).
"""

import io
from dataclasses import asdict, dataclass, field
from pathlib import Path

import trimesh

ALLOWED_EXT = ("stl", "3mf")

# Если самая длинная сторона меньше этого — возможно, файл в дюймах.
TINY_MM = 10.0
# Самый большой размер, который вообще считаем осмысленным (1 м). Больше — явная ошибка единиц.
HUGE_MM = 1000.0


class MeshError(ValueError):
    """Файл не удалось прочитать как 3D-модель. Текст — для клиента."""


@dataclass
class MeshInfo:
    triangles: int
    vertices: int
    bbox_mm: dict[str, float]  # {"x": .., "y": .., "z": ..}
    volume_cm3: float
    surface_cm2: float
    watertight: bool
    repaired: bool  # True, если дыры удалось закрыть автоматически
    unit_hint: str  # "mm" | "maybe_inches"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _load_mesh(data: bytes, ext: str) -> trimesh.Trimesh:
    """Читает STL или 3MF в одну сетку. 3MF может содержать несколько объектов — склеиваем."""
    try:
        loaded = trimesh.load(io.BytesIO(data), file_type=ext, force="mesh")
    except Exception as e:  # trimesh кидает разное: BadZipFile, StopIteration, ValueError...
        raise MeshError("Не удалось прочитать файл как 3D-модель.") from e

    if isinstance(loaded, trimesh.Scene):
        if loaded.is_empty:
            raise MeshError("В файле нет геометрии.")
        loaded = loaded.to_mesh()

    if not isinstance(loaded, trimesh.Trimesh) or loaded.is_empty or len(loaded.faces) == 0:
        raise MeshError("В файле нет геометрии.")
    return loaded


def inspect_mesh(
    data: bytes, ext: str, print_bed: tuple[float, float, float] = (250.0, 210.0, 220.0)
) -> MeshInfo:
    """Главная функция: байты файла + расширение → MeshInfo. Бросает MeshError."""
    ext = ext.lower().lstrip(".")
    if ext not in ALLOWED_EXT:
        raise MeshError(f"Поддерживаются только {', '.join(ALLOWED_EXT)}.")

    mesh = _load_mesh(data, ext)
    warnings: list[str] = []

    repaired = False
    if not mesh.is_watertight:
        # Пробуем закрыть дыры. Если получилось — объём будет точным.
        trimesh.repair.fill_holes(mesh)
        repaired = bool(mesh.is_watertight)
        if repaired:
            warnings.append("holes_filled")
        else:
            warnings.append("not_watertight")

    # Объём трёхмерной «вывернутой» сетки получается отрицательным — берём модуль.
    volume_mm3 = abs(float(mesh.volume))
    extents = [float(v) for v in mesh.extents]
    bbox = {"x": round(extents[0], 2), "y": round(extents[1], 2), "z": round(extents[2], 2)}
    longest = max(extents)

    unit_hint = "mm"
    if longest <= TINY_MM:
        unit_hint = "maybe_inches"
        warnings.append("tiny_maybe_inches")
    elif longest > HUGE_MM:
        warnings.append("huge_check_units")

    # Влезает ли в принтер хоть в какой-то ориентации по осям (без поворотов под углом).
    # Сравниваем отсортированные стороны: самая длинная с самой длинной стороной стола и т.д.
    if any(side > bed for side, bed in zip(sorted(extents), sorted(print_bed), strict=True)):
        warnings.append("exceeds_print_bed")

    if volume_mm3 <= 0:
        warnings.append("zero_volume")

    return MeshInfo(
        triangles=int(len(mesh.faces)),
        vertices=int(len(mesh.vertices)),
        bbox_mm=bbox,
        volume_cm3=round(volume_mm3 / 1000.0, 3),
        surface_cm2=round(float(mesh.area) / 100.0, 2),
        watertight=bool(mesh.is_watertight),
        repaired=repaired,
        unit_hint=unit_hint,
        warnings=warnings,
    )


def inspect_file(path: Path, print_bed: tuple[float, float, float]) -> MeshInfo:
    return inspect_mesh(path.read_bytes(), path.suffix, print_bed)
