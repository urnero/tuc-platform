"""API цены (B05).

GET  /api/v1/pricing                    — прайс для формы: материалы, постобработка, доставка,
                                          ступени тиража, минимальный заказ.
POST /api/v1/uploads/{id}/quote         — body {material, supports, qty, postprocess, delivery}.
                                          Берёт граммы и время из готового расчёта печати (B04)
                                          и считает цену. Если печать ещё не посчитана — 409:
                                          сначала POST /uploads/{id}/slice.
GET  /api/v1/quotes/{quote_id}          — сохранённый расчёт цены (его потом заказывает B06).

Расчёты лежат файлами: DATA_DIR/uploads/<id>/quotes/<quote_id>.json. В B06 переедут в БД.
"""

import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.pricing import PricingError, calc_price, load_pricing
from app.slice_jobs import load_record, slice_key
from app.slicer import SlicerError
from app.uploads import load_meta

router = APIRouter(prefix="/api/v1", tags=["quotes"])


class QuoteRequest(BaseModel):
    material: str = "PLA"
    supports: bool = False
    qty: int = Field(default=1, ge=1, le=10_000)
    postprocess: str = "none"
    delivery: str = "pickup"


def quotes_dir(upload_id: str) -> Path:
    return settings.data_dir / "uploads" / upload_id / "quotes"


def _save_quote(upload_id: str, quote: dict) -> dict:
    path = quotes_dir(upload_id) / f"{quote['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(quote, ensure_ascii=False, indent=2), "utf-8")
    return quote


QUOTE_ID_RE = re.compile(r"^[0-9a-f]{32}-[0-9a-f]{6}$")  # <upload_id>-<хвост>; защита от «../»


def load_quote(quote_id: str) -> dict | None:
    """Находит файл расчёта: id расчёта = <upload_id>-<случайный хвост>."""
    if not QUOTE_ID_RE.match(quote_id):
        return None
    upload_id = quote_id.rsplit("-", 1)[0]
    path = quotes_dir(upload_id) / f"{quote_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text("utf-8"))


@router.get("/pricing")
def get_pricing() -> dict:
    try:
        return load_pricing().public()
    except PricingError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/uploads/{upload_id}/quote", status_code=201)
def create_quote(upload_id: str, body: QuoteRequest) -> dict:
    meta = load_meta(upload_id)  # 404, если загрузки нет
    try:
        key = slice_key(body.material, body.supports)
    except SlicerError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    record = load_record(upload_id, key)
    if record is None or record["status"] != "done":
        status = record["status"] if record else "none"
        raise HTTPException(
            status_code=409,
            detail=f"Сначала рассчитайте печать (POST /uploads/{upload_id}/slice). "
            f"Статус расчёта: {status}.",
        )

    try:
        quote = calc_price(
            load_pricing(),
            material=body.material,
            material_g=float(record["result"]["filament_g"]),
            print_time_s=int(record["result"]["print_time_s"]),
            supports=body.supports,
            qty=body.qty,
            postprocess=body.postprocess,
            delivery=body.delivery,
        )
    except PricingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    data = {
        "id": f"{upload_id}-{secrets.token_hex(3)}",
        "upload_id": upload_id,
        "original_name": meta.get("original_name"),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "slice_key": key,
        **quote.to_dict(),
    }
    return _save_quote(upload_id, data)


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: str) -> dict:
    quote = load_quote(quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Расчёт не найден.")
    return quote
