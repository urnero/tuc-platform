"""Фоновые задачи (arq поверх Redis). Запуск: `arq app.worker.WorkerSettings`.

Контейнер worker (worker/Dockerfile) — это тот же код api плюс PrusaSlicer.
Задачи:
- slice_upload — посчитать печать для загрузки (B04);
- export_sheet — ночной экспорт заказов в Google-таблицу (B11), по расписанию cron.
Позже сюда добавится рендер превью (B20).
"""

import asyncio

from arq.connections import RedisSettings
from arq.cron import cron

from app.config import settings
from app.sheets import export_orders_job
from app.slice_jobs import run_slice


async def slice_upload(ctx: dict, upload_id: str, material: str, supports: bool = False) -> dict:
    """Слайсер — отдельный процесс, поэтому ждём его в потоке, не блокируя воркер."""
    return await asyncio.to_thread(run_slice, upload_id, material, supports)


async def export_sheet(ctx: dict) -> dict | None:
    """Переписать лист заказов в Google-таблице (app/sheets.py). Без ключей — пропуск."""
    return await asyncio.to_thread(export_orders_job)


def redis_settings() -> RedisSettings:
    # Пустой REDIS_URL бывает только в разработке без очереди — воркер тогда не запускают,
    # а API считает сам. Чтобы импорт модуля не падал, подставляем localhost.
    return RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")


class WorkerSettings:
    functions = [slice_upload, export_sheet]
    # Время — по часам контейнера (UTC): 02:05 UTC = 05:05 МСК, когда заказов уже не оформляют.
    cron_jobs = [cron(export_sheet, hour=2, minute=5, timeout=300)]
    redis_settings = redis_settings()
    max_jobs = 1  # слайсер грузит процессор целиком — по одной модели за раз
    job_timeout = settings.slice_timeout_s + 60
    keep_result = 3600
