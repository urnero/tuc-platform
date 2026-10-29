"""Заявка «цена по запросу» (B44): смолы (SLA) и всё, что слайсер не считает.

POST /api/v1/uploads/{upload_id}/request
     {material: "RESIN", qty: 1, name, phone, email?, comment?}
     → 201 {ok: true, telegram: true|false}  (telegram=false — бот не настроен)

Оплаты здесь нет: владелец получает заявку в Telegram (карточка со ссылкой на файл),
смотрит модель и называет цену клиенту сам. Заявка с контактами сохраняется в таблицу `leads`
— так она не потеряется, даже если Telegram выключен: список в админке /admin/leads.
Через ANONYMIZE_ORDERS_DAYS контакты стираются (app/anonymize.py). В `events` пишется
только факт заявки (`material_request`: material, qty, lead_id) — без данных клиента.

Почему не обычный заказ: формула цены (pricing.py) смолы не умеет — PrusaSlicer SLA-режим
мы не подключали (DECISIONS 2026-10-27 п. 3). Когда владелец захочет считать смолы
автоматически — это отдельная задача.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app import materials
from app.config import settings
from app.db import get_db
from app.events import track
from app.limits import orders_guard
from app.models import Lead
from app.orders import EMAIL_RE, PhoneError, normalize_phone
from app.telegram import esc, send_message, telegram_enabled
from app.uploads import load_meta

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["leads"])


class LeadRequest(BaseModel):
    material: str = Field(min_length=1, max_length=32)
    qty: int = Field(default=1, ge=1, le=10000)
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=1, max_length=32)
    email: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "email", "comment", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        try:
            return normalize_phone(v)
        except PhoneError as e:
            raise ValueError(str(e)) from e

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is not None and not EMAIL_RE.match(v):
            raise ValueError("Проверьте e-mail.")
        return v


def lead_text(upload_id: str, meta: dict, body: LeadRequest, material: materials.Material) -> str:
    """Карточка заявки для Telegram владельца (HTML)."""
    bbox = (meta.get("mesh") or {}).get("bbox_mm") or {}
    size = tuple(float(bbox.get(k, 0)) for k in ("x", "y", "z"))
    lines = [
        "📝 <b>Заявка: цена по запросу</b>",
        f"Материал: {esc(material.name)}",
        f"Тираж: {body.qty} шт.",
        f"Файл: {esc(meta.get('original_name', ''))}",
    ]
    if any(size):
        dims = " × ".join(f"{v:g}" for v in size)
        lines.append(f"Размер: {dims} мм")
        if material.max_mm and not materials.fits(size, material.max_mm):
            lines.append("⚠️ Больше области печати — частями или другим материалом")
    lines += [
        f"Клиент: {esc(body.name)}",
        f"Телефон: {esc(body.phone)}",
    ]
    if body.email:
        lines.append(f"E-mail: {esc(body.email)}")
    if body.comment:
        lines.append(f"Комментарий: {esc(body.comment)}")
    lines.append(f"Модель: {settings.site_url}/api/v1/uploads/{upload_id}/file")
    return "\n".join(lines)


@router.post("/uploads/{upload_id}/request", status_code=201, dependencies=[Depends(orders_guard)])
def create_lead(
    upload_id: str,
    body: LeadRequest,
    background: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    meta = load_meta(upload_id)  # 404, если загрузки нет
    material = materials.get(body.material)
    if material is None or not material.enabled:
        raise HTTPException(status_code=422, detail="Такого материала нет.")
    sent = telegram_enabled()
    lead = Lead(
        upload_id=upload_id,
        material=material.key,
        qty=body.qty,
        name=body.name,
        phone=body.phone,
        email=body.email,
        comment=body.comment,
        telegram_sent=sent,
    )
    db.add(lead)
    db.flush()  # нужен lead.id для события
    # Событие — одной транзакцией с заявкой. Контактов в нём нет (см. docstring модуля).
    track(
        "material_request",
        upload_id=upload_id,
        props={"material": material.key, "qty": body.qty, "lead_id": lead.id},
        db=db,
    )
    db.commit()
    if sent:
        text = lead_text(upload_id, meta, body, material)
        background.add_task(send_message, settings.telegram_owner_chat_id, text)
    else:
        log.info("telegram выключен: заявка № %s по %s — только в админке", lead.id, upload_id)
    return {"ok": True, "telegram": sent}
