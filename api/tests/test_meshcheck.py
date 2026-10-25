import pytest
from conftest import box_3mf, box_stl, open_box_stl

from app.meshcheck import MeshError, inspect_mesh


def test_box_stl_binary():
    info = inspect_mesh(box_stl(), "stl")
    assert info.triangles == 12
    assert info.bbox_mm == {"x": 20.0, "y": 30.0, "z": 40.0}
    assert info.volume_cm3 == pytest.approx(24.0)
    assert info.surface_cm2 == pytest.approx(52.0)  # 2*(20*30+30*40+20*40)/100
    assert info.watertight is True
    assert info.repaired is False
    assert info.unit_hint == "mm"
    assert info.warnings == []


def test_box_stl_ascii_same_result():
    assert (
        inspect_mesh(box_stl(ascii_fmt=True), "stl").to_dict()
        == inspect_mesh(box_stl(), "stl").to_dict()
    )


def test_box_3mf():
    info = inspect_mesh(box_3mf(), "3mf")
    assert info.bbox_mm == {"x": 20.0, "y": 30.0, "z": 40.0}
    assert info.volume_cm3 == pytest.approx(24.0)
    assert info.watertight is True


def test_extension_case_insensitive():
    assert inspect_mesh(box_stl(), ".STL").triangles == 12


def test_open_mesh_gets_repaired_or_flagged():
    info = inspect_mesh(open_box_stl(), "stl")
    # Одну недостающую грань trimesh закрывает сам.
    assert info.watertight is True
    assert info.repaired is True
    assert "holes_filled" in info.warnings
    assert info.volume_cm3 == pytest.approx(24.0)


def test_tiny_model_hints_inches():
    info = inspect_mesh(box_stl(1.0, 2.0, 3.0), "stl")
    assert info.unit_hint == "maybe_inches"
    assert "tiny_maybe_inches" in info.warnings


def test_huge_model_warns():
    info = inspect_mesh(box_stl(1500.0, 10.0, 10.0), "stl", print_bed=(2000, 2000, 2000))
    assert "huge_check_units" in info.warnings


def test_exceeds_print_bed_considers_rotation():
    # 300 по X, но стол 250×210×300: если положить вдоль Z — влезает.
    fits = inspect_mesh(box_stl(300.0, 20.0, 20.0), "stl", print_bed=(250, 210, 300))
    assert "exceeds_print_bed" not in fits.warnings
    too_big = inspect_mesh(box_stl(300.0, 20.0, 20.0), "stl", print_bed=(250, 210, 220))
    assert "exceeds_print_bed" in too_big.warnings


def test_garbage_stl_raises():
    with pytest.raises(MeshError):
        inspect_mesh(b"this is not a model", "stl")


def test_garbage_3mf_raises():
    with pytest.raises(MeshError):
        inspect_mesh(b"not a zip at all", "3mf")


def test_unknown_extension_raises():
    with pytest.raises(MeshError):
        inspect_mesh(box_stl(), "obj")


def test_inch_units_scale_everything():
    info = inspect_mesh(box_stl(1.0, 2.0, 3.0), "stl", units="inch")
    assert info.bbox_mm == {"x": 25.4, "y": 50.8, "z": 76.2}
    assert info.volume_cm3 == pytest.approx(6 * 25.4**3 / 1000, rel=1e-3)
    assert info.unit_hint == "mm"
    assert "tiny_maybe_inches" not in info.warnings


def test_bad_units_raise():
    with pytest.raises(MeshError):
        inspect_mesh(box_stl(), "stl", units="cm")


# --- 3MF как zip: защита от zip-бомбы (BUG [БЕЗОПАСНОСТЬ]) ---


def _zip_3mf(parts: dict[str, bytes]) -> bytes:
    """Собирает zip с заданными файлами внутри — «3MF» для проверки защиты."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_3mf_bomb_high_ratio_rejected():
    """Мегабайт пробелов сжимается в ~1 КБ (отношение ~1000×) — такой архив не распаковываем."""
    bomb = _zip_3mf({"3D/3dmodel.model": b" " * (1024 * 1024)})
    assert len(bomb) < 10 * 1024  # действительно «бомба»: маленький архив, большой внутри
    with pytest.raises(MeshError, match="сжатие"):
        inspect_mesh(bomb, "3mf")


def test_3mf_too_big_unpacked_rejected(monkeypatch):
    """Сумма размеров внутри архива больше лимита → отказ до trimesh (лимит занижен для теста)."""
    import os

    from app import meshcheck

    monkeypatch.setattr(meshcheck, "MAX_3MF_UNPACKED_MB", 1)
    # Случайные байты не сжимаются — отношение ~1×, срабатывает именно проверка размера.
    big = _zip_3mf({"3D/3dmodel.model": os.urandom(2 * 1024 * 1024)})
    with pytest.raises(MeshError, match="распакованном"):
        inspect_mesh(big, "3mf")


def test_3mf_too_many_entries_rejected(monkeypatch):
    from app import meshcheck

    monkeypatch.setattr(meshcheck, "MAX_3MF_ENTRIES", 5)
    many = _zip_3mf({f"f{i}.xml": b"<a/>" for i in range(6)})
    with pytest.raises(MeshError, match="много файлов"):
        inspect_mesh(many, "3mf")


def test_3mf_honest_archive_passes_check():
    """Настоящий 3MF (из trimesh) проходит все три проверки без ошибок."""
    from app.meshcheck import check_3mf_archive

    check_3mf_archive(box_3mf())
    assert inspect_mesh(box_3mf(), "3mf").bbox_mm == {"x": 20.0, "y": 30.0, "z": 40.0}


def test_3mf_declared_size_is_what_python_unpacks():
    """Опора защиты: Python при чтении обрезает запись по размеру из оглавления.

    Подменяем в архиве объявленный размер на меньший и убеждаемся, что zipfile отдаёт
    не больше объявленного (или ругается на CRC — тоже отказ) — значит, сумма file_size
    из оглавления и есть верхняя граница того, что развернётся в памяти.
    """
    import io
    import zipfile

    raw = _zip_3mf({"3D/3dmodel.model": b"x" * 1000})
    zf = zipfile.ZipFile(io.BytesIO(raw))
    info = zf.infolist()[0]
    info.file_size = 10  # «врём» в оглавлении
    try:
        data = zf.open(info).read()
    except zipfile.BadZipFile:
        return  # обрезал и не сошлась контрольная сумма — распаковка остановлена
    assert len(data) <= 10
