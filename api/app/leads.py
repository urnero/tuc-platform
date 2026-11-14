"""Заявка «цена по запросу» (B44): смолы (SLA) и всё, что слайсер не считает.

POST /api/v1/uploads/{upload_id}/request
     {material: "RESIN", qty: 1, name, phone, email?, comment?}
     → 201 {ok: true, telegram: bool, email: bool, delivered: bool}

Оплаты здесь нет: владелец получает заявку в Telegram (карточка со ссылкой на файл)
и/или письмом на OWNER_EMAIL (нужен SMTP_HOST, как для кабинета). `delivered=false` —
ни одного канала нет: заявка только в админке, и сайт честно говорит клиенту, что ответ
будет не сразу, и показывает контакты студии (web/lib/materials.ts::leadSentText).

смотрит модель и называет цену клиенту сам. Заявка с контактами сохраняется в таблицу `leads`
— так она не потеряется, даже если Telegram выключен: список в админке /admin/leads.
Через ANONYMIZE_ORDERS_DAYS контакты стираются (app/anonymize.py). В `events` пишется
только факт заявки (`material_request`: material, qty, lead_id) — без данных клиента.

Почему не обычный заказ: формула цены (pricing.py) смолы не умеет — PrusaSlicer SLA-режим
мы не подключали (DECISIONS 2026-10-27 п. 3). Когда владелец захочет считать смолы
автоматически — это отдельная задача.
"""

import logging
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app import materials
from app.config import settings
from app.db import get_db
from app.events import track
from app.limits import orders_guard
from app.mailer import mail_enabled, send_mail
from app.models import Lead
from app.orders import EMAIL_RE, PhoneError, normalize_phone
from app.telegram import esc as tg_esc
from app.telegram import send_message, telegram_enabled
from app.uploads import ID_RE, load_meta

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


def lead_text(
    upload_id: str,
    meta: dict,
    body: LeadRequest,
    material: materials.Material,
    html: bool = True,
) -> str:
    """Карточка заявки владельцу: HTML для Telegram (html=True) или простой текст для письма."""

    def esc(v: str) -> str:
        return tg_esc(v) if html else v

    bbox = (meta.get("mesh") or {}).get("bbox_mm") or {}
    size = tuple(float(bbox.get(k, 0)) for k in ("x", "y", "z"))
    lines = [
        "📝 <b>Заявка: цена по запросу</b>" if html else "Заявка: цена по запросу",
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
    by_email = bool(mail_enabled() and settings.owner_email)
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
    if by_email:
        subject = f"Заявка № {lead.id}: цена по запросу ({material.name})"
        text = lead_text(upload_id, meta, body, material, html=False)
        text += f"\nВсе заявки: {settings.site_url}/admin/leads"
        background.add_task(send_mail, settings.owner_email, subject, text)
    if not (sent or by_email):
        log.warning("нет Telegram и OWNER_EMAIL: заявка № %s — только в админке", lead.id)
    return {"ok": True, "telegram": sent, "email": by_email, "delivered": sent or by_email}


# --- Быстрые заявки (B52) -------------------------------------------------------------------
#
# POST /api/v1/leads/callback  JSON {phone, name?, comment?, page?, upload_id?}
#      — выходной попап «оставьте телефон, посчитаем вручную»: клиент ушёл, не дойдя до заказа.
# POST /api/v1/leads/brief     form-data name, phone, comment, email?, qty?, page?,
#                              photo? (jpg/png/webp/heic, до 10 МБ)
#      — «нет STL? пришлите фото или описание».
# Ответ как у заявки на смолу: {ok, lead_id, telegram, email, delivered}.
# Всё ложится в ту же таблицу `leads` (kind = callback / brief) → /admin/leads.
# В `events` — `quick_lead` с kind, lead_id, page и has_photo; контактов там нет.

PHOTO_MAX_MB = 10
# Первые байты файла → расширение. Проверяем содержимое, а не имя: имя клиент может подделать.
PHOTO_MAGIC: tuple[tuple[bytes, int, str], ...] = (
    (b"\xff\xd8\xff", 0, "jpg"),
    (b"\x89PNG\r\n\x1a\n", 0, "png"),
    (b"WEBP", 8, "webp"),
    (b"ftypheic", 4, "heic"),
    (b"ftypheix", 4, "heic"),
    (b"ftypmif1", 4, "heic"),
)
KIND_TITLES = {
    "material": "цена по запросу",
    "callback": "перезвонить",
    "brief": "без модели (фото/описание)",
}


def photo_ext(data: bytes) -> str | None:
    """jpg / png / webp / heic по первым байтам; None — не картинка."""
    for magic, offset, ext in PHOTO_MAGIC:
        if data[offset : offset + len(magic)] == magic:
            if ext == "webp" and data[:4] != b"RIFF":
                continue
            return ext
    return None


def leads_root() -> Path:
    return Path(settings.data_dir) / "leads"


def lead_photo_path(lead: Lead) -> Path | None:
    """Файл фото заявки или None (нет фото / стёрто обезличиванием)."""
    if not lead.photo:
        return None
    path = leads_root() / str(lead.id) / lead.photo
    return path if path.is_file() else None


def delete_lead_photo(lead_id: int) -> None:
    """Стереть папку с фото заявки (обезличивание, app/anonymize.py)."""
    shutil.rmtree(leads_root() / str(lead_id), ignore_errors=True)


def clean_page(page: str | None) -> str | None:
    """Только путь страницы: без домена, ?параметров и #якоря, до 200 символов."""
    if not page:
        return None
    path = page.split("#", 1)[0].split("?", 1)[0].strip()
    if not path.startswith("/"):
        return None
    return path[:200]


def _phone_or_422(phone: str) -> str:
    try:
        return normalize_phone(phone)
    except PhoneError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _blank(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


class CallbackRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=32)
    name: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=2000)
    page: str | None = Field(default=None, max_length=500)
    upload_id: str | None = Field(default=None, max_length=32)

    @field_validator("name", "comment", "page", "upload_id", mode="before")
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


def quick_lead_text(lead: Lead, html: bool = True) -> str:
    """Карточка быстрой заявки владельцу: HTML для Telegram или простой текст для письма."""

    def esc(v: str) -> str:
        return tg_esc(v) if html else v

    title = f"Заявка № {lead.id}: {KIND_TITLES.get(lead.kind, lead.kind)}"
    lines = [f"📞 <b>{esc(title)}</b>" if html else title]
    if lead.name:
        lines.append(f"Клиент: {esc(lead.name)}")
    lines.append(f"Телефон: {esc(lead.phone)}")
    if lead.email:
        lines.append(f"E-mail: {esc(lead.email)}")
    if lead.kind == "brief" and lead.qty > 1:
        lines.append(f"Тираж: {lead.qty} шт.")
    if lead.comment:
        label = "Что нужно" if lead.kind == "brief" else "Комментарий"
        lines.append(f"{label}: {esc(lead.comment)}")
    if lead.page:
        lines.append(f"Ушёл со страницы: {esc(lead.page)}")
    if lead.upload_id:
        lines.append(f"Модель: {settings.site_url}/upload/{lead.upload_id}")
    if lead.photo:
        lines.append(f"Фото: {settings.site_url}/admin/leads/{lead.id}/photo")
    return "\n".join(lines)


def _save_and_notify(
    db: Session, lead: Lead, background: BackgroundTasks, photo: tuple[bytes, str] | None = None
) -> dict:
    """Общий хвост быстрых заявок: в БД, событие, фото на диск, Telegram и письмо."""
    sent = telegram_enabled()
    by_email = bool(mail_enabled() and settings.owner_email)
    lead.telegram_sent = sent
    db.add(lead)
    db.flush()  # нужен lead.id для события и папки фото
    if photo is not None:
        data, ext = photo
        folder = leads_root() / str(lead.id)
        folder.mkdir(parents=True, exist_ok=True)
        lead.photo = f"photo.{ext}"
        (folder / lead.photo).write_bytes(data)
    track(
        "quick_lead",
        upload_id=lead.upload_id,
        props={
            "kind": lead.kind,
            "lead_id": lead.id,
            "page": lead.page,
            "has_photo": photo is not None,
        },
        db=db,
    )
    db.commit()
    if sent:
        background.add_task(send_message, settings.telegram_owner_chat_id, quick_lead_text(lead))
    if by_email:
        subject = f"Заявка № {lead.id}: {KIND_TITLES[lead.kind]}"
        text = quick_lead_text(lead, html=False)
        text += f"\nВсе заявки: {settings.site_url}/admin/leads"
        background.add_task(send_mail, settings.owner_email, subject, text)
    if not (sent or by_email):
        log.warning("нет Telegram и OWNER_EMAIL: заявка № %s — только в админке", lead.id)
    return {
        "ok": True,
        "lead_id": lead.id,
        "telegram": sent,
        "email": by_email,
        "delivered": sent or by_email,
    }


@router.post("/leads/callback", status_code=201, dependencies=[Depends(orders_guard)])
def create_callback(
    body: CallbackRequest,
    background: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Выходной попап: «оставьте телефон — посчитаем вручную»."""
    upload_id = body.upload_id if body.upload_id and ID_RE.match(body.upload_id) else None
    lead = Lead(
        kind="callback",
        upload_id=upload_id,
        qty=1,
        name=body.name or "",
        phone=body.phone,
        comment=body.comment,
        page=clean_page(body.page),
    )
    return _save_and_notify(db, lead, background)


async def _read_photo(photo: UploadFile) -> tuple[bytes, str]:
    limit = PHOTO_MAX_MB * 1024 * 1024
    data = await photo.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"Фото больше {PHOTO_MAX_MB} МБ.")
    ext = photo_ext(data)
    if ext is None:
        raise HTTPException(status_code=415, detail="Фото — в формате JPG, PNG, WEBP или HEIC.")
    return data, ext


@router.post("/leads/brief", status_code=201, dependencies=[Depends(orders_guard)])
async def create_brief(
    background: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    name: Annotated[str, Form(max_length=200)],
    phone: Annotated[str, Form(max_length=32)],
    comment: Annotated[str, Form(max_length=2000)],
    email: Annotated[str | None, Form(max_length=200)] = None,
    qty: Annotated[int, Form(ge=1, le=10000)] = 1,
    page: Annotated[str | None, Form(max_length=500)] = None,
    photo: UploadFile | None = None,
) -> dict:
    """«Нет файла модели»: описание задачи и, по желанию, фото детали или эскиза."""
    name_v = _blank(name)
    comment_v = _blank(comment)
    email_v = _blank(email)
    if not name_v:
        raise HTTPException(status_code=422, detail="Укажите имя.")
    if not comment_v or len(comment_v) < 5:
        raise HTTPException(status_code=422, detail="Опишите, что нужно напечатать.")
    if email_v and not EMAIL_RE.match(email_v):
        raise HTTPException(status_code=422, detail="Проверьте e-mail.")
    phone_v = _phone_or_422(phone)
    photo_data = await _read_photo(photo) if photo is not None and photo.filename else None
    lead = Lead(
        kind="brief",
        qty=qty,
        name=name_v,
        phone=phone_v,
        email=email_v,
        comment=comment_v,
        page=clean_page(page),
    )
    return _save_and_notify(db, lead, background, photo_data)
