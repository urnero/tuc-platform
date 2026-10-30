"""API расчёта печати (B04).

POST /api/v1/uploads/{id}/slice        — body {material: "PLA", supports: false}.
                                          Ставит задачу в очередь (Redis) или, если REDIS_URL пуст,
                                          считает сразу. Отвечает записью расчёта.
GET  /api/v1/uploads/{id}/slice?material=PLA&supports=false
                                        — запись расчёта: status queued|running|done|error,
                                          result.print_time_s, result.filament_g, ...
GET  /api/v1/materials                 — материалы для формы (B44): `materials` — ключи, которые
                                          считает слайсер; `on_request` — смолы (цена по запросу);
                                          `items` — справочник config/materials.yaml для карточек.

Готовый расчёт не пересчитываем: тот же материал и поддержки → отдаём сохранённое.
Исключение — единицы модели поменялись (PATCH /uploads/{id} {units}): запись для
других единиц устарела, считаем заново.

Застрявшие расчёты (worker упал, Redis был недоступен) — см. app/jobs.py: запись
`queued`/`running` старше таймаута становится `error`, POST ставит задачу заново.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app import jobs, materials
from app.config import settings
from app.slice_jobs import (
    load_record,
    new_record,
    record_path,
    run_slice,
    save_record,
    slice_key,
)
from app.slicer import SlicerError
from app.uploads import load_meta

router = APIRouter(prefix="/api/v1", tags=["slices"])


class SliceRequest(BaseModel):
    material: str = "PLA"
    supports: bool = False


@router.get("/materials")
def list_materials() -> dict:
    return {
        "materials": list(materials.sliceable()),
        "on_request": list(materials.on_request()),
        "items": [m.to_dict() for m in materials.enabled()],
    }


async def _enqueue(
    request: Request, upload_id: str, material: str, supports: bool, units: str, attempt: int = 0
) -> None:
    """Кладёт задачу в arq (общий пул — app/jobs.py).

    _job_id — чтобы одна и та же загрузка не попала в очередь дважды.
    Единицы в id: после смены «мм → дюймы» это уже другой расчёт.
    attempt > 0 — повтор после брошенной задачи, id другой (см. jobs.retry_job_id)."""
    job_id = jobs.retry_job_id(f"slice:{upload_id}:{material}:{supports}:{units}", attempt)
    await jobs.enqueue(request, "slice_upload", upload_id, material, supports, job_id=job_id)


def _settle(upload_id: str, record: dict | None) -> dict | None:
    """Брошенная запись (queued/running старше таймаута) → error, сохраняем."""
    return jobs.settle(record, lambda rec: save_record(upload_id, rec))


@router.post("/uploads/{upload_id}/slice", status_code=202)
async def create_slice(upload_id: str, body: SliceRequest, request: Request) -> dict:
    meta = load_meta(upload_id)  # 404, если загрузки нет
    units = meta.get("units", "mm")
    try:
        key = slice_key(body.material, body.supports)
    except SlicerError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    # Деталь больше области печати материала — в очередь не ставим: слайсер упал бы
    # или положил модель за край стола. Клиенту — понятный текст, что делать.
    problem = materials.size_problem(materials.model_size_mm(meta), body.material.upper())
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    record = _settle(upload_id, load_record(upload_id, key, units=units))
    if record and record["status"] in ("queued", "running", "done"):
        return record  # уже считаем или уже посчитали (для текущих единиц)

    attempt = jobs.next_attempt(record)  # была ошибка/брошена → повтор под новым id задачи
    record = new_record(upload_id, body.material, body.supports, units)
    record["attempt"] = attempt
    save_record(upload_id, record)
    if settings.redis_url:
        try:
            await _enqueue(request, upload_id, record["material"], body.supports, units, attempt)
        except jobs.QueueUnavailable:
            # В очередь не попало — записи быть не должно, иначе клиент ждал бы её вечно.
            record_path(upload_id, key).unlink(missing_ok=True)
            raise jobs.queue_unavailable() from None
        return record
    # Без очереди — считаем здесь же. Для разработки и тестов, в проде так не делаем.
    return await run_in_threadpool(run_slice, upload_id, record["material"], body.supports)


@router.get("/uploads/{upload_id}/slice")
def get_slice(upload_id: str, material: str = "PLA", supports: bool = False) -> dict:
    meta = load_meta(upload_id)
    try:
        key = slice_key(material, supports)
    except SlicerError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    record = _settle(upload_id, load_record(upload_id, key, units=meta.get("units", "mm")))
    if record is None:
        raise HTTPException(status_code=404, detail="Расчёт ещё не запрашивали.")
    return record
