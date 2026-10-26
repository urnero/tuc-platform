"""Загрузка моделей клиентом (B02).

POST /api/v1/uploads          — принять STL/3MF (≤ MAX_UPLOAD_MB), проверить сетку, сохранить.
GET  /api/v1/uploads/{id}     — данные загрузки (габариты, объём, предупреждения).
GET  /api/v1/uploads/{id}/file — сам файл (нужен 3D-просмотру в браузере, B03).
PATCH /api/v1/uploads/{id}    — клиент говорит, в каких единицах файл (mm | inch); пересчитываем
                                габариты и удаляем старые расчёты печати и цены (slices/, quotes/)
                                и разборку на детали для раскраски (paint/).

Хранение: DATA_DIR/uploads/<id>/model.<ext> + meta.json.
БД появится в B06 вместе с заказами — тогда meta.json переедет в таблицу models.
"""

import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings
from app.events import track
from app.limits import uploads_guard
from app.meshcheck import ALLOWED_EXT, UNITS, MeshError, inspect_file, inspect_mesh

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])

CHUNK = 1024 * 1024  # читаем файл по 1 МБ
ID_RE = re.compile(r"^[0-9a-f]{32}$")  # uuid4.hex — защита от «../» в пути


def uploads_root() -> Path:
    return settings.data_dir / "uploads"


def upload_dir(upload_id: str) -> Path:
    if not ID_RE.match(upload_id):
        raise HTTPException(status_code=404, detail="Загрузка не найдена.")
    return uploads_root() / upload_id


def _safe_name(name: str | None) -> str:
    """Оставляем только имя файла без пути, не длиннее 200 символов."""
    base = Path(name or "model").name
    return base[:200] or "model"


def _ext_of(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=415,
            detail=f"Поддерживаются только файлы {', '.join(ALLOWED_EXT)}.",
        )
    return ext


async def _read_limited(file: UploadFile, limit_bytes: int) -> bytes:
    """Читает файл по кускам и останавливается, как только лимит превышен."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Файл больше {settings.max_upload_mb} МБ.",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=422, detail="Пустой файл.")
    return b"".join(chunks)


@router.post("", status_code=201, dependencies=[Depends(uploads_guard)])
async def create_upload(file: UploadFile) -> dict:
    original_name = _safe_name(file.filename)
    ext = _ext_of(original_name)
    data = await _read_limited(file, settings.max_upload_mb * 1024 * 1024)

    # Разбор сетки — тяжёлая операция, не блокируем event loop.
    try:
        info = await run_in_threadpool(inspect_mesh, data, ext, settings.print_bed)
    except MeshError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    upload_id = uuid.uuid4().hex
    folder = upload_dir(upload_id)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / f"model.{ext}").write_bytes(data)

    meta = {
        "id": upload_id,
        "original_name": original_name,
        "ext": ext,
        "size_bytes": len(data),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "units": "mm",  # в каких единицах координаты файла; mesh всегда в мм
        "mesh": info.to_dict(),
    }
    _save_meta(folder, meta)
    # Воронка (B12): шаг «загрузил модель». Ошибка БД сюда не долетит — track() её проглотит.
    await run_in_threadpool(
        track,
        "upload",
        upload_id=upload_id,
        props={
            "ext": ext,
            "size_bytes": len(data),
            "watertight": info.watertight,
            "warnings": info.warnings,
        },
    )
    return meta


def _save_meta(folder: Path, meta: dict) -> None:
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")


def load_meta(upload_id: str) -> dict:
    meta_path = upload_dir(upload_id) / "meta.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail="Загрузка не найдена.")
    return json.loads(meta_path.read_text("utf-8"))


@router.get("/{upload_id}")
def get_upload(upload_id: str) -> dict:
    return load_meta(upload_id)


class UploadPatch(BaseModel):
    units: str  # "mm" | "inch"


@router.patch("/{upload_id}")
async def patch_upload(upload_id: str, patch: UploadPatch) -> dict:
    """Клиент посмотрел модель и сказал: «файл в дюймах». Пересчитываем габариты и объём."""
    if patch.units not in UNITS:
        raise HTTPException(status_code=422, detail=f"Единицы: {', '.join(UNITS)}.")
    meta = load_meta(upload_id)
    if meta.get("units") == patch.units:
        return meta
    path = upload_dir(upload_id) / f"model.{meta['ext']}"
    try:
        info = await run_in_threadpool(inspect_file, path, settings.print_bed, patch.units)
    except MeshError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    meta["units"] = patch.units
    meta["mesh"] = info.to_dict()
    _save_meta(upload_dir(upload_id), meta)
    # Расчёты печати (граммы, часы, G-code) и цены сделаны для старых единиц —
    # в дюймах модель в 25,4³ ≈ 16 000 раз больше. Удаляем, клиент посчитает заново.
    # Заказы не страдают: у заказа свой снимок расчёта в БД (колонка orders.quote).
    # Разборка на детали для раскраски (B31) тоже сделана в старых единицах.
    for sub in ("slices", "quotes", "paint"):
        shutil.rmtree(upload_dir(upload_id) / sub, ignore_errors=True)
    return meta


@router.get("/{upload_id}/file")
def get_upload_file(upload_id: str) -> FileResponse:
    meta = load_meta(upload_id)
    path = upload_dir(upload_id) / f"model.{meta['ext']}"
    return FileResponse(path, media_type="application/octet-stream", filename=meta["original_name"])
