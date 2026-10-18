"""Общие заготовки для тестов: тестовые модели и временная папка DATA_DIR."""

import sys
from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def box_stl(x=20.0, y=30.0, z=40.0, ascii_fmt=False) -> bytes:
    """Коробка x×y×z мм в формате STL (binary или ascii)."""
    box = trimesh.creation.box(extents=(x, y, z))
    data = box.export(file_type="stl_ascii" if ascii_fmt else "stl")
    return data.encode() if isinstance(data, str) else data


def box_3mf(x=20.0, y=30.0, z=40.0) -> bytes:
    box = trimesh.creation.box(extents=(x, y, z))
    return trimesh.exchange.threemf.export_3MF(box)


def open_box_stl() -> bytes:
    """Коробка без одной грани — незамкнутая сетка."""
    box = trimesh.creation.box(extents=(20.0, 30.0, 40.0))
    broken = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-1])
    return broken.export(file_type="stl")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Каждый тест пишет файлы в свою временную папку."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


@pytest.fixture
def client(data_dir):
    return TestClient(app)


REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_SLICER = Path(__file__).resolve().parent / "fake_slicer.py"


@pytest.fixture
def fake_slicer(monkeypatch):
    """Вместо PrusaSlicer — tests/fake_slicer.py; профили — настоящие из profiles/; без Redis."""
    monkeypatch.setattr(settings, "prusa_slicer_bin", f"{sys.executable} {FAKE_SLICER}")
    monkeypatch.setattr(settings, "profiles_dir", REPO_ROOT / "profiles")
    monkeypatch.setattr(settings, "redis_url", "")
    return FAKE_SLICER
