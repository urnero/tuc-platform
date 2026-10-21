"""Превью модели в PNG без видеокарты (B20).

На сервере нет OpenGL, поэтому картинку рисуем сами: numpy проецирует треугольники сетки
на плоскость, Pillow закрашивает их по одному от дальних к ближним («алгоритм художника»).
Для моделей каталога (сотни — десятки тысяч треугольников) это доли секунды.

Камера: ортографическая, смотрит на модель сверху-спереди-справа, как на чертеже-изометрии.
Свет: один источник со стороны камеры чуть сверху-слева + рассеянный, чтобы тени не были чёрными.

render_png(mesh) → байты PNG. Картинка кэшируется вызывающим кодом (catalog.py).
"""

import io

import numpy as np
import trimesh
from PIL import Image, ImageDraw

# Откуда смотрит камера (вектор из центра модели к камере), оси как у принтера: Z — вверх.
VIEW_DIR = np.array([1.0, -1.2, 0.9])
# Откуда светит лампа.
LIGHT_DIR = np.array([0.4, -1.0, 1.4])

BASE_COLOR = (79, 191, 178)  # тот же бирюзовый, что у ModelViewer в браузере (#4fbfb2)
BACKGROUND = (255, 255, 255, 0)  # прозрачный фон — картинка ложится на любой цвет карточки
MARGIN = 0.08  # поля вокруг модели, доля стороны
SUPERSAMPLE = 2  # рисуем в 2 раза крупнее и уменьшаем — края становятся гладкими


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def _camera_basis() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Оси экрана в координатах модели: right, up и направление на камеру."""
    toward = _unit(VIEW_DIR)
    right = _unit(np.cross(np.array([0.0, 0.0, 1.0]), toward))
    up = np.cross(toward, right)
    return right, up, toward


def render_png(
    mesh: trimesh.Trimesh, size: int = 512, color: tuple[int, int, int] = BASE_COLOR
) -> bytes:
    """Рисует сетку в квадрат size×size px. Пустая сетка → прозрачная картинка."""
    big = size * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), BACKGROUND)
    if mesh.is_empty or len(mesh.faces) == 0:
        return _to_png(img, size)

    right, up, toward = _camera_basis()
    mesh = _split_big_triangles(mesh)
    verts = np.asarray(mesh.vertices, dtype=float) - mesh.bounds.mean(axis=0)
    # Проекция: экранные x, y и глубина (чем больше, тем ближе к камере).
    sx = verts @ right
    sy = verts @ up
    depth = verts @ toward

    # Вписываем модель в квадрат с полями, сохраняя пропорции.
    span = max(float(sx.max() - sx.min()), float(sy.max() - sy.min()), 1e-9)
    scale = big * (1 - 2 * MARGIN) / span
    px = (sx - (sx.max() + sx.min()) / 2) * scale + big / 2
    py = big / 2 - (sy - (sy.max() + sy.min()) / 2) * scale  # на экране y растёт вниз

    faces = np.asarray(mesh.faces)
    normals = np.asarray(mesh.face_normals)
    # Грани, повёрнутые от камеры, не видны — не рисуем (вдвое меньше работы).
    facing = normals @ toward > 0
    faces, normals = faces[facing], normals[facing]
    if len(faces) == 0:
        return _to_png(img, size)

    # Освещение: рассеянное 35 % + направленное до 65 %.
    light = _unit(LIGHT_DIR)
    shade = 0.35 + 0.65 * np.clip(normals @ light, 0, 1)
    colors = (np.array(color, dtype=float) * shade[:, None]).round().astype(int)

    # От дальних к ближним: ближние закрашивают дальние.
    order = np.argsort(depth[faces].mean(axis=1))
    draw = ImageDraw.Draw(img)
    for i in order:
        tri = faces[i]
        pts = [(float(px[v]), float(py[v])) for v in tri]
        fill = (int(colors[i][0]), int(colors[i][1]), int(colors[i][2]), 255)
        # outline тем же цветом — иначе между треугольниками остаются волосяные щели
        draw.polygon(pts, fill=fill, outline=fill)
    return _to_png(img, size)


def _split_big_triangles(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Режет крупные треугольники на мелкие.

    «Алгоритм художника» сортирует треугольники по средней глубине, и у фигур из
    пересекающихся блоков (стенки лотка, крючок) большой дальний треугольник может
    закрыть маленький ближний. Мелкие треугольники сортируются почти без ошибок.
    Делаем это только для простых сеток — у подробных моделей треугольники и так мелкие.
    """
    if len(mesh.faces) > 5000:
        return mesh
    max_edge = float(mesh.extents.max()) / 24
    try:
        return mesh.subdivide_to_size(max_edge=max_edge, max_iter=6)
    except Exception:  # на всякий случай: рисуем как есть
        return mesh


def _to_png(img: Image.Image, size: int) -> bytes:
    if img.width != size:
        img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
