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
