"""Фоновые задачи (arq поверх Redis). Запуск: `arq app.worker.WorkerSettings`.

Контейнер worker (worker/Dockerfile) — это тот же код api плюс PrusaSlicer.
Задачи:
- slice_upload — посчитать печать для загрузки (B04).
Позже сюда добавятся рендер превью (B20) и экспорт в Google-таблицу (B11).
"""

import asyncio

from arq.connections import RedisSettings

from app.config import settings
from app.slice_jobs import run_slice


async def slice_upload(ctx: dict, upload_id: str, material: str, supports: bool = False) -> dict:
    """Слайсер — отдельный процесс, поэтому ждём его в потоке, не блокируя воркер."""
    return await asyncio.to_thread(run_slice, upload_id, material, supports)


def redis_settings() -> RedisSettings:
    # Пустой REDIS_URL бывает только в разработке без очереди — воркер тогда не запускают,
    # а API считает сам. Чтобы импорт модуля не падал, подставляем localhost.
    return RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")


class WorkerSettings:
    functions = [slice_upload]
    redis_settings = redis_settings()
    max_jobs = 1  # слайсер грузит процессор целиком — по одной модели за раз
    job_timeout = settings.slice_timeout_s + 60
    keep_result = 3600
