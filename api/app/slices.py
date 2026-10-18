"""API расчёта печати (B04).

POST /api/v1/uploads/{id}/slice        — body {material: "PLA", supports: false}.
                                          Ставит задачу в очередь (Redis) или, если REDIS_URL пуст,
                                          считает сразу. Отвечает записью расчёта.
GET  /api/v1/uploads/{id}/slice?material=PLA&supports=false
                                        — запись расчёта: status queued|running|done|error,
                                          result.print_time_s, result.filament_g, ...
GET  /api/v1/materials                 — список материалов для формы.

Готовый расчёт не пересчитываем: тот же материал и поддержки → отдаём сохранённое.
"""

from arq import create_pool
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.config import settings
from app.slice_jobs import load_record, new_record, run_slice, save_record, slice_key
from app.slicer import MATERIALS, SlicerError
from app.uploads import load_meta
from app.worker import redis_settings

router = APIRouter(prefix="/api/v1", tags=["slices"])


class SliceRequest(BaseModel):
    material: str = "PLA"
    supports: bool = False


@router.get("/materials")
def list_materials() -> dict:
    return {"materials": list(MATERIALS)}


async def _enqueue(request: Request, upload_id: str, material: str, supports: bool) -> None:
    """Кладёт задачу в arq. Пул соединений с Redis держим один на процесс (в app.state)."""
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is None:
        pool = await create_pool(redis_settings())
        request.app.state.arq_pool = pool
    # _job_id — чтобы одна и та же загрузка не попала в очередь дважды
    job_id = f"slice:{upload_id}:{material}:{supports}"
    await pool.enqueue_job("slice_upload", upload_id, material, supports, _job_id=job_id)


@router.post("/uploads/{upload_id}/slice", status_code=202)
async def create_slice(upload_id: str, body: SliceRequest, request: Request) -> dict:
    load_meta(upload_id)  # 404, если загрузки нет
    try:
        key = slice_key(body.material, body.supports)
    except SlicerError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    record = load_record(upload_id, key)
    if record and record["status"] in ("queued", "running", "done"):
        return record  # уже считаем или уже посчитали

    record = save_record(upload_id, new_record(upload_id, body.material, body.supports))
    if settings.redis_url:
        await _enqueue(request, upload_id, record["material"], body.supports)
        return record
    # Без очереди — считаем здесь же. Для разработки и тестов, в проде так не делаем.
    return await run_in_threadpool(run_slice, upload_id, record["material"], body.supports)


@router.get("/uploads/{upload_id}/slice")
def get_slice(upload_id: str, material: str = "PLA", supports: bool = False) -> dict:
    load_meta(upload_id)
    try:
        record = load_record(upload_id, slice_key(material, supports))
    except SlicerError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if record is None:
        raise HTTPException(status_code=404, detail="Расчёт ещё не запрашивали.")
    return record
