"""Общие заготовки для тестов: тестовые модели и временная папка DATA_DIR."""

import sys
from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, get_engine, reset_engine
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


@pytest.fixture(autouse=True)
def no_limits(monkeypatch):
    """Ограничения частоты и проверка диска (app/limits.py) в обычных тестах выключены —
    иначе сотни загрузок с одного «testclient» упёрлись бы в 429. Тесты лимитов включают их сами."""
    from app.limits import limiter

    monkeypatch.setattr(settings, "rate_limit_uploads_per_min", 0)
    monkeypatch.setattr(settings, "rate_limit_orders_per_min", 0)
    monkeypatch.setattr(settings, "rate_limit_login_per_min", 0)
    monkeypatch.setattr(settings, "min_free_disk_gb", 0)
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def no_telegram_getme(monkeypatch):
    """Имя бота (B34) API спрашивает у Telegram (getMe). В тестах сети нет: запрос «падает»
    сразу, кэш ответа сбрасывается. Тесты getMe подменяют `tg.httpx.get` сами."""
    import httpx

    from app import telegram as tg

    def no_network(*a, **k):
        raise httpx.ConnectError("нет сети в тестах")

    monkeypatch.setattr(tg.httpx, "get", no_network)
    tg.forget_bot_username()
    yield
    tg.forget_bot_username()


@pytest.fixture(autouse=True)
def notify_in_foreground(monkeypatch):
    """Уведомления клиенту (B34) в тестах шлём в том же потоке, чтобы их можно было поймать."""
    from app import notify

    monkeypatch.setattr(notify, "IN_BACKGROUND", False)


@pytest.fixture(autouse=True)
def sheets_in_foreground(monkeypatch):
    """Живой лог в Google-таблицу (B47) в тестах — в том же потоке и без пауз между попытками."""
    from app import sheets

    monkeypatch.setattr(sheets, "IN_BACKGROUND", False)
    monkeypatch.setattr(sheets, "RETRY_DELAYS_S", ())


@pytest.fixture(autouse=True)
def drive_in_foreground(monkeypatch):
    """Копирование в Google Drive (B46) в тестах — в том же потоке и без пауз между попытками."""
    from app import drive

    monkeypatch.setattr(drive, "IN_BACKGROUND", False)
    monkeypatch.setattr(drive, "RETRY_DELAYS_S", ())


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Каждый тест пишет файлы в свою временную папку."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Вместо Postgres — файл SQLite во временной папке, таблицы из app/models.py."""
    import app.models  # noqa: F401  — регистрирует таблицы в Base.metadata

    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'test.db'}")
    reset_engine()
    Base.metadata.create_all(get_engine())
    yield get_engine()
    get_engine().dispose()
    reset_engine()


@pytest.fixture
def client(data_dir, db):
    return TestClient(app)


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def materials_yaml(monkeypatch):
    """Справочник материалов (B44) — настоящий config/materials.yaml из корня репо."""
    monkeypatch.setattr(settings, "materials_path", REPO_ROOT / "config" / "materials.yaml")


FAKE_SLICER = Path(__file__).resolve().parent / "fake_slicer.py"


@pytest.fixture
def fake_slicer(monkeypatch):
    """Вместо PrusaSlicer — tests/fake_slicer.py; профили — настоящие из profiles/; без Redis."""
    monkeypatch.setattr(settings, "prusa_slicer_bin", f"{sys.executable} {FAKE_SLICER}")
    monkeypatch.setattr(settings, "profiles_dir", REPO_ROOT / "profiles")
    monkeypatch.setattr(settings, "redis_url", "")
    return FAKE_SLICER


FAKE_OPENSCAD = Path(__file__).resolve().parent / "fake_openscad.py"


@pytest.fixture
def fake_openscad(monkeypatch):
    """Вместо OpenSCAD — tests/fake_openscad.py (пишет коробку); без Redis — строим в API."""
    monkeypatch.setattr(settings, "openscad_bin", f"{sys.executable} {FAKE_OPENSCAD}")
    monkeypatch.setattr(settings, "redis_url", "")
    return FAKE_OPENSCAD
