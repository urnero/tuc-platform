"""Автоудаление файлов моделей по срокам из политики ПДн (B15, /policy, раздел 6).

Что обещано клиенту:
- файл модели, по которому заказ не оформлен, живёт не дольше 30 дней после загрузки;
- файл модели по выполненному заказу — не дольше 12 месяцев (чтобы повторить заказ).

Что удаляем: папку загрузки целиком — DATA_DIR/uploads/<id>/ (сам файл, meta.json,
расчёты печати с G-code, расчёты цены). Записи в БД (orders, payments, events) не трогаем:
заказ хранит снимок расчёта цены и имя файла, так что история и учёт остаются.
После удаления в админке у заказа просто нет кнопки «Скачать файл».

Правила по папке загрузки:
- по ней нет заказов → удаляем, если загрузка старше CLEANUP_UPLOADS_DAYS (возраст —
  `created_at` из meta.json, без meta.json — время изменения папки);
- есть заказы, и хоть один ещё в работе (new / paid / printing / ready) → не трогаем;
- все заказы закрыты (done / cancelled) → удаляем, когда последний из них закрыт
  дольше CLEANUP_ORDER_FILES_DAYS назад (по `orders.updated_at`).

Запуск: cron в worker каждую ночь (app/worker.py) и руками —
`python -m app.cleanup` (посмотреть, что удалится: `python -m app.cleanup --dry-run`).
Значение 0 у любого срока выключает это правило.
"""

import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_factory
from app.models import Order

log = logging.getLogger(__name__)

ID_RE = re.compile(r"^[0-9a-f]{32}$")  # имя папки загрузки — uuid4.hex, другие не трогаем
# Заказ закрыт — файл клиенту больше не нужен для работы, остаётся только «повторить заказ».
CLOSED_STATUSES = ("done", "cancelled")


@dataclass
class Candidate:
    """Папка, которую пора удалить, и почему."""

    upload_id: str
    path: Path
    reason: str  # no_order | orders_closed
    age_days: int
    size_bytes: int


@dataclass
class CleanupReport:
    checked: int = 0  # сколько папок загрузок просмотрели
    deleted: list[Candidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def freed_bytes(self) -> int:
        return sum(c.size_bytes for c in self.deleted)

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "deleted": len(self.deleted),
            "freed_mb": round(self.freed_bytes / (1024 * 1024), 1),
            "no_order": sum(1 for c in self.deleted if c.reason == "no_order"),
            "orders_closed": sum(1 for c in self.deleted if c.reason == "orders_closed"),
            "errors": self.errors,
            "dry_run": self.dry_run,
        }


def uploads_root() -> Path:
    return settings.data_dir / "uploads"


def _as_utc(dt: datetime) -> datetime:
    """SQLite отдаёт время без зоны — считаем, что это UTC (так его и пишет utcnow())."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def upload_created_at(folder: Path) -> datetime:
    """Когда загрузили: `created_at` из meta.json, иначе — время изменения папки."""
    meta_path = folder / "meta.json"
    try:
        raw = json.loads(meta_path.read_text("utf-8")).get("created_at")
        if raw:
            return _as_utc(datetime.fromisoformat(raw))
    except (OSError, ValueError, AttributeError):
        pass
    return datetime.fromtimestamp(folder.stat().st_mtime, UTC)


def folder_size(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def orders_by_upload(db: Session) -> dict[str, tuple[bool, datetime]]:
    """Для каждой загрузки: (есть ли заказ ещё в работе, когда последний раз менялся её заказ)."""
    result: dict[str, tuple[bool, datetime]] = {}
    rows = db.execute(select(Order.upload_id, Order.status, Order.updated_at)).all()
    for upload_id, status, updated_at in rows:
        updated_at = _as_utc(updated_at)
        active, last = result.get(upload_id, (False, updated_at))
        result[upload_id] = (active or status not in CLOSED_STATUSES, max(last, updated_at))
    return result


def find_candidates(db: Session, now: datetime | None = None) -> tuple[list[Candidate], int]:
    """Пройти по DATA_DIR/uploads и отобрать папки, чей срок вышел. Ничего не удаляет."""
    now = now or datetime.now(UTC)
    root = uploads_root()
    if not root.is_dir():
        return [], 0

    orders = orders_by_upload(db)
    upload_ttl = timedelta(days=settings.cleanup_uploads_days)
    order_ttl = timedelta(days=settings.cleanup_order_files_days)
    candidates: list[Candidate] = []
    checked = 0

    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not ID_RE.match(folder.name):
            continue  # чужие файлы и папки не наши — пропускаем
        checked += 1
        upload_id = folder.name

        if upload_id in orders:
            has_active, last_change = orders[upload_id]
            if has_active or settings.cleanup_order_files_days <= 0:
                continue
            age = now - last_change
            if age < order_ttl:
                continue
            reason = "orders_closed"
        else:
            if settings.cleanup_uploads_days <= 0:
                continue
            age = now - upload_created_at(folder)
            if age < upload_ttl:
                continue
            reason = "no_order"

        candidates.append(
            Candidate(
                upload_id=upload_id,
                path=folder,
                reason=reason,
                age_days=age.days,
                size_bytes=folder_size(folder),
            )
        )
    return candidates, checked


def run_cleanup(db: Session, now: datetime | None = None, dry_run: bool = False) -> CleanupReport:
    """Удалить всё, чей срок вышел. dry_run=True — только перечислить."""
    candidates, checked = find_candidates(db, now)
    report = CleanupReport(checked=checked, dry_run=dry_run)
    for c in candidates:
        if not dry_run:
            try:
                shutil.rmtree(c.path)
            except OSError as e:
                report.errors.append(f"{c.upload_id}: {e}")
                log.warning("Очистка: не удалилась папка %s — %s", c.path, e)
                continue
        report.deleted.append(c)
        log.info(
            "Очистка: %s %s (%s, %d дн., %.1f МБ)",
            "удалил бы" if dry_run else "удалена",
            c.upload_id,
            "без заказа" if c.reason == "no_order" else "заказы закрыты",
            c.age_days,
            c.size_bytes / (1024 * 1024),
        )
    log.info(
        "Очистка файлов: просмотрено %d, удалено %d, освобождено %.1f МБ%s",
        report.checked,
        len(report.deleted),
        report.freed_bytes / (1024 * 1024),
        " (пробный прогон)" if dry_run else "",
    )
    return report


def cleanup_job(dry_run: bool = False) -> dict:
    """Для cron в worker и CLI: своя сессия БД."""
    with session_factory()() as db:
        return run_cleanup(db, dry_run=dry_run).to_dict()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in args
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = cleanup_job(dry_run=dry_run)
    verb = "удалилось бы" if dry_run else "удалено"
    print(
        f"Просмотрено папок: {result['checked']}, {verb}: {result['deleted']} "
        f"(без заказа — {result['no_order']}, по закрытым заказам — {result['orders_closed']}), "
        f"{result['freed_mb']} МБ."
    )
    for err in result["errors"]:
        print(f"Ошибка: {err}", file=sys.stderr)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
