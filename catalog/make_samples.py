"""Стартовые модели каталога (B20) — простые фигуры из примитивов trimesh.

Это заглушки, чтобы каталог не был пустым: владелец заменит их своими STL
(положить файл в catalog/models/, строку — в catalog/catalog.yaml). Перегенерировать:
    cd api && pip install manifold3d && python ../catalog/make_samples.py
(manifold3d нужен только этому скрипту — для объединения и вычитания фигур; в API его нет.)
Все размеры — в миллиметрах, модели стоят на столе (минимальный Z = 0).
"""

from pathlib import Path

import numpy as np
import trimesh
from trimesh.boolean import difference, union
from trimesh.creation import annulus, box, cylinder

OUT = Path(__file__).resolve().parent / "models"


def at(mesh: trimesh.Trimesh, x=0.0, y=0.0, z=0.0) -> trimesh.Trimesh:
    """Сдвигает фигуру так, чтобы её центр оказался в (x, y, z)."""
    mesh.apply_translation([x, y, z])
    return mesh


def on_floor(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Ставит модель на стол: минимальный Z = 0, центр XY = 0."""
    lo, hi = mesh.bounds
    mesh.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    return mesh


def prism(points_xy: list[tuple[float, float]], height: float) -> trimesh.Trimesh:
    """Призма из выпуклого многоугольника (обход против часовой стрелки) высотой height."""
    n = len(points_xy)
    bottom = [(x, y, 0.0) for x, y in points_xy]
    top = [(x, y, height) for x, y in points_xy]
    verts = np.array(bottom + top)
    faces = []
    for i in range(1, n - 1):  # дно — веером, нормаль вниз
        faces.append([0, i + 1, i])
    for i in range(1, n - 1):  # крышка — веером, нормаль вверх
        faces.append([n, n + i, n + i + 1])
    for i in range(n):  # боковые стенки
        j = (i + 1) % n
        faces.append([i, j, n + j])
        faces.append([i, n + j, n + i])
    return trimesh.Trimesh(vertices=verts, faces=faces, process=True)


def calibration_cube() -> trimesh.Trimesh:
    return box(extents=(20, 20, 20))


def washer_m8() -> trimesh.Trimesh:
    # внутренний Ø 8,4, наружный Ø 24, толщина 3
    return annulus(r_min=4.2, r_max=12.0, height=3.0, sections=96)


def spacer() -> trimesh.Trimesh:
    # втулка-проставка под винт M5: Ø 10 × 20, отверстие Ø 5,5
    return annulus(r_min=2.75, r_max=5.0, height=20.0, sections=64)


def coaster() -> trimesh.Trimesh:
    # подставка под кружку Ø 90 × 4 с бортиком 2 мм высотой 3
    base = cylinder(radius=45.0, height=4.0, sections=128)
    rim = at(annulus(r_min=43.0, r_max=45.0, height=3.0, sections=128), z=3.5)
    return union([base, rim])


def door_stop() -> trimesh.Trimesh:
    # клин 100 × 40, высота 25: профиль — треугольник, ширина 40
    profile = prism([(0.0, 0.0), (100.0, 0.0), (0.0, 25.0)], 40.0)
    # призма построена в плоскости XY, поворачиваем: высота профиля → Z, толщина → Y
    profile.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    return profile


def wall_hook() -> trimesh.Trimesh:
    # крючок на саморез: пластина 30×6×60, рожок 25×6×8 с упором 6×6×14, отверстие Ø 4,5
    plate = at(box(extents=(30, 6, 60)), z=30)
    arm = at(box(extents=(30, 25, 8)), y=12.5 - 3, z=4)
    tip = at(box(extents=(30, 6, 14)), y=25 - 3 - 3, z=7)
    hole = cylinder(radius=2.25, height=20, sections=48)
    hole.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    hole = at(hole, z=45)
    return difference([union([plate, arm, tip]), hole])


def tray() -> trimesh.Trimesh:
    # лоток-органайзер 120 × 80 × 30, стенки и дно 2 мм
    w, d, h, t = 120.0, 80.0, 30.0, 2.0
    outer = at(box(extents=(w, d, h)), z=h / 2)
    inner = at(box(extents=(w - 2 * t, d - 2 * t, h)), z=h / 2 + t)
    return difference([outer, inner])


SAMPLES = {
    "calibration-cube": calibration_cube,
    "washer-m8": washer_m8,
    "spacer-m5": spacer,
    "coaster": coaster,
    "door-stop": door_stop,
    "wall-hook": wall_hook,
    "tray-120x80": tray,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, make in SAMPLES.items():
        mesh = on_floor(make())
        if not mesh.is_watertight:
            raise SystemExit(f"{slug}: сетка не замкнута, печатать нельзя")
        path = OUT / f"{slug}.stl"
        path.write_bytes(mesh.export(file_type="stl"))
        x, y, z = mesh.extents
        print(f"{path.name}: {x:.0f}×{y:.0f}×{z:.0f} мм, {len(mesh.faces)} треугольников")


if __name__ == "__main__":
    main()
