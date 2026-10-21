"""Автоудаление файлов моделей по срокам политики ПДн (B15, app/cleanup.py)."""

import json
import os
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app import cleanup, worker
from app.config import settings
from app.models import Order

NOW = datetime(2026, 10, 21, 1, 35, tzinfo=UTC)


def _upload(data_dir, days_ago: float, with_meta: bool = True) -> str:
    """Папка загрузки «как после POST /uploads»: model.stl, meta.json, расчёты."""
    upload_id = secrets.token_hex(16)
    folder = data_dir / "uploads" / upload_id
    (folder / "slices").mkdir(parents=True)
    (folder / "model.stl").write_bytes(b"x" * 2048)
    (folder / "slices" / "PLA.gcode").write_bytes(b"g" * 1024)
    created = NOW - timedelta(days=days_ago)
    if with_meta:
        meta = {"id": upload_id, "created_at": created.isoformat(timespec="seconds")}
        (folder / "meta.json").write_text(json.dumps(meta), "utf-8")
    else:
        # без meta.json возраст берём по времени изменения папки
        os.utime(folder, (created.timestamp(), created.timestamp()))
    return upload_id


def _order(db, upload_id: str, status: str, closed_days_ago: float) -> Order:
    when = NOW - timedelta(days=closed_days_ago)
    order = Order(
        token=secrets.token_hex(16),
        status=status,
        created_at=when - timedelta(days=3),
        updated_at=when,
        customer_name="Иван",
        phone="+79991234567",
        delivery="pickup",
        upload_id=upload_id,
        quote_id=f"{upload_id}-abc123",
        original_name="box.stl",
        material="PLA",
        total=900,
        quote={"total": 900},
    )
    db.add(order)
    db.commit()
    return order


@pytest.fixture
def session(db):
    with Session(db) as s:
        yield s


def _exists(data_dir, upload_id: str) -> bool:
    return (data_dir / "uploads" / upload_id).is_dir()


def test_uploads_without_order(data_dir, session):
    old = _upload(data_dir, days_ago=31)
    on_edge = _upload(data_dir, days_ago=30.5)
    fresh = _upload(data_dir, days_ago=29)
    old_no_meta = _upload(data_dir, days_ago=45, with_meta=False)
    fresh_no_meta = _upload(data_dir, days_ago=2, with_meta=False)

    report = cleanup.run_cleanup(session, now=NOW)

    assert not _exists(data_dir, old)
    assert not _exists(data_dir, on_edge)
    assert not _exists(data_dir, old_no_meta)
    assert _exists(data_dir, fresh)
    assert _exists(data_dir, fresh_no_meta)
    assert report.checked == 5
    assert sorted(c.upload_id for c in report.deleted) == sorted([old, on_edge, old_no_meta])
    assert {c.reason for c in report.deleted} == {"no_order"}
    assert report.freed_bytes >= 3 * 3072  # модель + G-code (+ meta.json) у каждой
    assert report.errors == []


def test_order_in_progress_keeps_files(data_dir, session):
    # Заказ в работе — файл нужен печати, сколько бы ни прошло времени.
    for status in ("new", "paid", "printing", "ready"):
        upload_id = _upload(data_dir, days_ago=900)
        _order(session, upload_id, status, closed_days_ago=800)
        cleanup.run_cleanup(session, now=NOW)
        assert _exists(data_dir, upload_id), status


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_closed_orders_after_a_year(data_dir, session, status):
    old = _upload(data_dir, days_ago=900)
    _order(session, old, status, closed_days_ago=366)
    recent = _upload(data_dir, days_ago=900)  # загрузка старая, но заказ закрыли недавно
    _order(session, recent, status, closed_days_ago=100)

    report = cleanup.run_cleanup(session, now=NOW)

    assert not _exists(data_dir, old)
    assert _exists(data_dir, recent)
    assert [c.reason for c in report.deleted] == ["orders_closed"]
    assert report.deleted[0].age_days == 366


def test_several_orders_on_one_upload(data_dir, session):
    # Один файл — несколько заказов: держим, пока жив хоть один; срок — от последнего закрытого.
    upload_id = _upload(data_dir, days_ago=900)
    _order(session, upload_id, "done", closed_days_ago=700)
    active = _order(session, upload_id, "printing", closed_days_ago=10)
    cleanup.run_cleanup(session, now=NOW)
    assert _exists(data_dir, upload_id)

    active.status = "done"
    session.commit()
    cleanup.run_cleanup(session, now=NOW)
    assert _exists(data_dir, upload_id)  # закрыт 10 дней назад — рано

    cleanup.run_cleanup(session, now=NOW + timedelta(days=370))
    assert not _exists(data_dir, upload_id)


def test_dry_run_and_foreign_files(data_dir, session):
    old = _upload(data_dir, days_ago=100)
    root = data_dir / "uploads"
    (root / "README.txt").write_text("не трогать")
    (root / "not-an-upload").mkdir()
    (root / "not-an-upload" / "x.bin").write_bytes(b"1")
    os.utime(root / "not-an-upload", (0, 0))

    report = cleanup.run_cleanup(session, now=NOW, dry_run=True)
    assert [c.upload_id for c in report.deleted] == [old]
    assert report.dry_run and report.to_dict()["dry_run"]
    assert _exists(data_dir, old)  # пробный прогон ничего не удаляет

    cleanup.run_cleanup(session, now=NOW)
    assert not _exists(data_dir, old)
    assert (root / "README.txt").is_file()
    assert (root / "not-an-upload" / "x.bin").is_file()


def test_zero_disables_rule(data_dir, session, monkeypatch):
    no_order = _upload(data_dir, days_ago=500)
    closed = _upload(data_dir, days_ago=500)
    _order(session, closed, "done", closed_days_ago=400)

    monkeypatch.setattr(settings, "cleanup_uploads_days", 0)
    report = cleanup.run_cleanup(session, now=NOW)
    assert _exists(data_dir, no_order)
    assert not _exists(data_dir, closed)
    assert report.to_dict()["orders_closed"] == 1

    monkeypatch.setattr(settings, "cleanup_order_files_days", 0)
    closed2 = _upload(data_dir, days_ago=500)
    _order(session, closed2, "done", closed_days_ago=400)
    cleanup.run_cleanup(session, now=NOW)
    assert _exists(data_dir, closed2)


def test_no_uploads_dir(data_dir, session):
    report = cleanup.run_cleanup(session, now=NOW)
    assert report.to_dict() == {
        "checked": 0,
        "deleted": 0,
        "editor_builds": 0,
        "freed_mb": 0,
        "no_order": 0,
        "orders_closed": 0,
        "errors": [],
        "dry_run": False,
    }


def test_admin_shows_order_without_file(client, data_dir, session, monkeypatch):
    # После удаления файла карточка заказа в админке открывается, а скачивание отвечает 404.
    monkeypatch.setattr(settings, "admin_password", "secret")
    upload_id = _upload(data_dir, days_ago=900)
    order = _order(session, upload_id, "done", closed_days_ago=400)
    auth = ("admin", "secret")
    assert client.get(f"/admin/orders/{order.id}/file", auth=auth).status_code == 200

    cleanup.run_cleanup(session, now=NOW)

    assert client.get(f"/admin/orders/{order.id}", auth=auth).status_code == 200
    assert client.get(f"/admin/orders/{order.id}/file", auth=auth).status_code == 404
    assert client.get(f"/api/v1/uploads/{upload_id}").status_code == 404


def test_cli_and_cron(data_dir, db, capsys):
    old = _upload(data_dir, days_ago=40)
    fresh = _upload(data_dir, days_ago=1)

    assert cleanup.main(["--dry-run"]) == 0
    assert "удалилось бы: 1" in capsys.readouterr().out
    assert _exists(data_dir, old)

    assert cleanup.main([]) == 0
    out = capsys.readouterr().out
    assert "удалено: 1" in out and "без заказа — 1" in out
    assert not _exists(data_dir, old) and _exists(data_dir, fresh)

    assert worker.cleanup_files in worker.WorkerSettings.functions
    assert [c.name for c in worker.WorkerSettings.cron_jobs] == [
        "cron:cleanup_files",
        "cron:export_sheet",
    ]
