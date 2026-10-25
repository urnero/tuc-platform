"""Задача «посчитать печать» для загрузки (B04).

Результат лежит рядом с моделью: DATA_DIR/uploads/<id>/slices/<ключ>.json,
где ключ — материал и наличие поддержек: PLA, PLA_supports, PETG, ...
Там же остаётся G-code — он потом пойдёт на принтер.

Статусы записи: queued → running → done | error.

В записи хранятся единицы модели (`units`: mm | inch), для которых она посчитана.
Если клиент потом переключил «файл в дюймах», граммы и часы из старой записи
не годятся (разница в 25,4³ ≈ 16 000 раз) — такая запись считается устаревшей
и не отдаётся (см. load_record), а PATCH units к тому же удаляет папку slices/.

Кто запускает:
- worker (arq, app/worker.py) — в проде;
- сам API синхронно — если REDIS_URL пустой (разработка без Redis, тесты).
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.slicer import MATERIALS, SlicerError, slice_model


def slice_key(material: str, supports: bool) -> str:
    material = material.upper()
    if material not in MATERIALS:
        raise SlicerError(f"Материал: {', '.join(MATERIALS)}.")
    return f"{material}_supports" if supports else material


def slices_dir(upload_id: str) -> Path:
    return settings.data_dir / "uploads" / upload_id / "slices"


def record_path(upload_id: str, key: str) -> Path:
    return slices_dir(upload_id) / f"{key}.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_record(upload_id: str, key: str, units: str | None = None) -> dict | None:
    """Запись расчёта. С `units` — только если она посчитана для этих единиц,
    иначе None: запись для других единиц — устаревшая, как будто её нет."""
    path = record_path(upload_id, key)
    if not path.is_file():
        return None
    record = json.loads(path.read_text("utf-8"))
    if units is not None and record.get("units", "mm") != units:
        return None
    return record


def save_record(upload_id: str, record: dict) -> dict:
    path = record_path(upload_id, record["key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


def new_record(upload_id: str, material: str, supports: bool, units: str = "mm") -> dict:
    return {
        "upload_id": upload_id,
        "key": slice_key(material, supports),
        "material": material.upper(),
        "supports": supports,
        "units": units,  # единицы модели на момент расчёта
        "status": "queued",
        "created_at": _now(),
        "finished_at": None,
        "error": None,
        "result": None,  # заполняется из SliceResult.to_dict()
    }


def run_slice(upload_id: str, material: str, supports: bool = False) -> dict:
    """Сама работа: читает meta.json загрузки, зовёт слайсер, пишет результат в запись."""
    key = slice_key(material, supports)
    record = load_record(upload_id, key) or new_record(upload_id, material, supports)
    record["status"] = "running"
    save_record(upload_id, record)

    folder = settings.data_dir / "uploads" / upload_id
    try:
        meta = json.loads((folder / "meta.json").read_text("utf-8"))
        model_path = folder / f"model.{meta['ext']}"
        units = meta.get("units", "mm")
        record["units"] = units  # считаем в тех единицах, что стоят у модели сейчас
        result = slice_model(
            model_path,
            slices_dir(upload_id),
            material,
            units=units,
            supports=supports,
        )
        record.update(status="done", result=result.to_dict(), error=None)
    except (SlicerError, OSError, KeyError, ValueError) as e:
        record.update(status="error", error=str(e))
    record["finished_at"] = _now()
    return save_record(upload_id, record)
