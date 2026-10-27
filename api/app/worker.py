"""Фоновые задачи (arq поверх Redis). Запуск: `arq app.worker.WorkerSettings`.

Контейнер worker (worker/Dockerfile) — это тот же код api плюс PrusaSlicer.
Задачи:
- slice_upload — посчитать печать для загрузки (B04);
- build_editor — построить STL в параметрическом редакторе через OpenSCAD (B21);
- emboss_upload — нанести надпись/логотип на загруженную модель (B30): OpenSCAD + trimesh;
- paint_upload — собрать 3MF с деталями модели в выбранных цветах (B31): trimesh;
- export_sheet — ночной экспорт заказов в Google-таблицу (B11), по расписанию cron;
- cleanup_files — ночное удаление файлов моделей по срокам из политики ПДн (B15), cron;
- anonymize_orders — ночное обезличивание заказов старше 5 лет (B35), cron.
"""

import asyncio

from arq.cron import cron

from app.anonymize import anonymize_job
from app.cleanup import cleanup_job
from app.editors import run_build
from app.emboss import run_emboss
from app.jobs import job_timeout_s, redis_settings
from app.paint import run_paint
from app.sheets import export_orders_job
from app.slice_jobs import run_slice


async def slice_upload(ctx: dict, upload_id: str, material: str, supports: bool = False) -> dict:
    """Слайсер — отдельный процесс, поэтому ждём его в потоке, не блокируя воркер."""
    return await asyncio.to_thread(run_slice, upload_id, material, supports)


async def build_editor(ctx: dict, slug: str, build_id: str) -> dict:
    """OpenSCAD — тоже отдельный процесс, ждём его в потоке."""
    return await asyncio.to_thread(run_build, slug, build_id)


async def emboss_upload(ctx: dict, upload_id: str, job_id: str) -> dict:
    """Тиснение: OpenSCAD строит надпись, trimesh соединяет её с моделью — всё в потоке."""
    return await asyncio.to_thread(run_emboss, upload_id, job_id)


async def paint_upload(ctx: dict, upload_id: str, job_id: str) -> dict:
    """Раскраска по частям: trimesh режет модель на детали и пишет 3MF — в потоке."""
    return await asyncio.to_thread(run_paint, upload_id, job_id)


async def export_sheet(ctx: dict) -> dict | None:
    """Переписать лист заказов в Google-таблице (app/sheets.py). Без ключей — пропуск."""
    return await asyncio.to_thread(export_orders_job)


async def cleanup_files(ctx: dict) -> dict:
    """Удалить загрузки без заказа старше 30 дней и файлы закрытых заказов старше года."""
    return await asyncio.to_thread(cleanup_job)


async def anonymize_orders(ctx: dict) -> dict:
    """Стереть данные клиента в заказах, закрытых больше 5 лет назад (app/anonymize.py)."""
    return await asyncio.to_thread(anonymize_job)


class WorkerSettings:
    functions = [
        slice_upload,
        build_editor,
        emboss_upload,
        paint_upload,
        export_sheet,
        cleanup_files,
        anonymize_orders,
    ]
    # Время — по часам контейнера (UTC), ночью по МСК, когда заказов уже не оформляют:
    # 01:35 UTC = 04:35 МСК — чистка файлов; 01:50 UTC = 04:50 МСК — обезличивание заказов;
    # 02:05 UTC = 05:05 МСК — экспорт в Google-таблицу (уже без данных обезличенных заказов).
    cron_jobs = [
        cron(cleanup_files, hour=1, minute=35, timeout=600),
        cron(anonymize_orders, hour=1, minute=50, timeout=300),
        cron(export_sheet, hour=2, minute=5, timeout=300),
    ]
    redis_settings = redis_settings()
    max_jobs = 1  # слайсер грузит процессор целиком — по одной модели за раз
    # Таймаут задачи — там же, где API решает, что задача брошена (app/jobs.py).
    job_timeout = job_timeout_s()
    keep_result = 3600
