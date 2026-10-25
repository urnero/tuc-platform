"""API цены (B05).

GET  /api/v1/pricing                    — прайс для формы: материалы, постобработка, доставка,
                                          ступени тиража, минимальный заказ.
POST /api/v1/uploads/{id}/quote         — body {material, supports, qty, postprocess, delivery}.
                                          Берёт граммы и время из готового расчёта печати (B04)
                                          и считает цену. Если печать ещё не посчитана — 409:
                                          сначала POST /uploads/{id}/slice.
GET  /api/v1/quotes/{quote_id}          — сохранённый расчёт цены (его потом заказывает B06).
                                          Расчёт действует QUOTE_TTL_HOURS (24 ч): цены в
                                          pricing.yaml могли измениться. Старше — 410 Gone,
                                          в ответе есть `expires_at`.

Расчёты лежат файлами: DATA_DIR/uploads/<id>/quotes/<quote_id>.json. В B06 переедут в БД.
"""

import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.events import track
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


def quote_expires_at(quote: dict) -> datetime | None:
    """Когда расчёт перестаёт действовать: created_at + QUOTE_TTL_HOURS. None = без срока."""
    if settings.quote_ttl_hours <= 0:
        return None
    created = quote.get("created_at")
    if not created:
        # Расчёт без даты (старый формат) считаем просроченным: цена по нему ненадёжна.
        return datetime.fromtimestamp(0, UTC)
    return datetime.fromisoformat(created) + timedelta(hours=settings.quote_ttl_hours)


def quote_is_expired(quote: dict) -> bool:
    expires = quote_expires_at(quote)
    return expires is not None and datetime.now(UTC) >= expires


def with_expiry(quote: dict) -> dict:
    """Расчёт для ответа API: плюс `expires_at` (ISO, UTC) или null, если срока нет."""
    expires = quote_expires_at(quote)
    return quote | {"expires_at": expires.isoformat(timespec="seconds") if expires else None}


def quote_expired_detail() -> str:
    return f"Расчёт устарел (действует {settings.quote_ttl_hours} ч). Рассчитайте цену заново."


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

    # Расчёт печати должен быть для текущих единиц модели: после «мм → дюймы» старый не годится.
    record = load_record(upload_id, key, units=meta.get("units", "mm"))
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
        "units": meta.get("units", "mm"),  # единицы модели, по которым посчитаны граммы и часы
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "slice_key": key,
        **quote.to_dict(),
    }
    _save_quote(upload_id, data)
    # Воронка (B12): шаг «посчитал цену».
    track(
        "quote",
        upload_id=upload_id,
        quote_id=data["id"],
        props={
            "material": quote.material,
            "supports": quote.supports,
            "qty": quote.qty,
            "postprocess": quote.postprocess,
            "delivery": quote.delivery,
            "total": quote.total,
        },
    )
    return with_expiry(data)


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: str) -> dict:
    quote = load_quote(quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Расчёт не найден.")
    if quote_is_expired(quote):
        raise HTTPException(status_code=410, detail=quote_expired_detail())
    return with_expiry(quote)
