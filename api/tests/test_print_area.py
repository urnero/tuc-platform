"""Область печати: стол слайсера, PRINT_BED_MM и max_mm материалов не расходятся,
а слишком большая деталь не попадает в очередь расчёта (BUG QA 2026-10-29)."""

from conftest import REPO_ROOT, box_stl

from app import materials, slicer
from app.config import Settings, settings


def _read_env_example(key: str) -> str:
    for line in (REPO_ROOT / ".env.example").read_text("utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].split("#", 1)[0].strip()
    raise AssertionError(f"{key} нет в .env.example")


def test_printer_ini_bed_matches_print_bed(monkeypatch):
    monkeypatch.setattr(settings, "profiles_dir", REPO_ROOT / "profiles")
    bed = slicer.printer_bed()
    assert bed == (256.0, 256.0, 256.0)
    # значение по умолчанию и пример .env — тот же стол
    assert Settings.model_fields["print_bed_mm"].default == "256x256x256"
    assert _read_env_example("PRINT_BED_MM") == "256x256x256"


def test_every_fdm_max_mm_fits_slicer_bed(monkeypatch):
    """Если сайт пропустил деталь по max_mm материала — у слайсера она тоже влезет."""
    monkeypatch.setattr(settings, "profiles_dir", REPO_ROOT / "profiles")
    bed = slicer.printer_bed()
    for key in materials.sliceable():
        m = materials.get(key)
        assert m.max_mm, f"{key}: нет max_mm в config/materials.yaml"
        assert all(a <= b for a, b in zip(m.max_mm, bed, strict=True)), key


def test_size_problem_texts():
    assert materials.size_problem((240, 240, 20), "PLA") is None
    assert materials.size_problem(None, "PLA") is None
    text = materials.size_problem((252, 20, 20), "TPU")
    assert text and "252 × 20 × 20" in text and "250 × 250 × 250" in text
    assert "частями" in text
    # слова, которые сайт прячет как «техническую ошибку», в тексте не используем
    assert "слайсер" not in text.lower() and "профил" not in text.lower()


def test_model_size_from_meta():
    assert materials.model_size_mm({"mesh": {"bbox_mm": {"x": 1, "y": 2, "z": 3}}}) == (1, 2, 3)
    assert materials.model_size_mm({}) is None


def _upload(client, x, y, z) -> str:
    data = box_stl(x, y, z)
    r = client.post("/api/v1/uploads", files={"file": ("box.stl", data, "model/stl")})
    assert r.status_code == 201
    return r.json()["id"]


def test_slice_api_big_flat_part_fits(client, fake_slicer):
    """240×240×20 — влезает в 256×256 (на старом столе 250×210 не влезала)."""
    upload_id = _upload(client, 240, 240, 20)
    r = client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "done"


def test_slice_api_rejects_too_big_before_queue(client, fake_slicer):
    upload_id = _upload(client, 300, 20, 20)
    r = client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    assert r.status_code == 422
    assert "не помещается" in r.json()["detail"]
    # записи расчёта нет — клиент не ждёт вечно
    assert not (settings.data_dir / "uploads" / upload_id / "slices").exists()


def test_slice_api_checks_material_area(client, fake_slicer):
    """252 мм: PLA (256) — можно, TPU (250) — нельзя."""
    upload_id = _upload(client, 252, 20, 20)
    ok = client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    assert ok.status_code == 202
    bad = client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "tpu"})
    assert bad.status_code == 422
    assert "TPU" in bad.json()["detail"]


def test_slice_api_inch_units_make_part_too_big(client, fake_slicer):
    upload_id = _upload(client, 20, 30, 40)  # в дюймах — 508 × 762 × 1016 мм
    assert client.patch(f"/api/v1/uploads/{upload_id}", json={"units": "inch"}).status_code == 200
    r = client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    assert r.status_code == 422
