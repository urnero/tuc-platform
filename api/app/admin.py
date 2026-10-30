"""Админка владельца (B09): простые HTML-страницы прямо из API, за basic auth.

GET  /admin                         — переход на список заказов.
GET  /admin/orders                  — таблица заказов: фильтр по статусу, поиск (номер, телефон,
                                      имя, e-mail, файл), страницы по 50.
GET  /admin/orders.csv              — те же заказы файлом CSV (для Excel / pandas).
GET  /admin/orders/{id}             — карточка: клиент, состав, разложение цены, платежи,
                                      смена статуса, скачивание файлов.
POST /admin/orders/{id}/status      — поставить статус (форма из карточки).
GET  /admin/orders/{id}/file        — файл модели клиента (STL/3MF).
GET  /admin/orders/{id}/gcode       — G-code, если расчёт печати делал настоящий слайсер.
GET  /admin/leads                   — заявки «цена по запросу» (смолы, B44), новые сверху.

Почему HTML из FastAPI, а не страница в Next: basic auth сам работает в браузере при
переходе по ссылке (на скачивание файла тоже), не нужен ни вход, ни сессии, ни JS.
Логин и пароль — ADMIN_USER / ADMIN_PASSWORD в .env; пустой пароль = админка выключена.
Caddy и next.config отправляют /admin/* в api.

Смена статуса — та же `orders.change_status`, что у бота (B07) и ЮKassa (B08).
"""

import csv
import io
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import materials
from app.config import settings
from app.db import get_db
from app.events import funnel, funnel_percents
from app.export import COLUMNS, MSK, fmt_dt, order_rows, paid_at_by_order
from app.models import ORDER_STATUSES, Lead, Order, Payment
from app.orders import StatusError, change_status, order_number, parse_order_number
from app.telegram import (
    ACTIVE_STATUSES,
    DELIVERY_LABELS,
    NEXT_STATUSES,
    POSTPROCESS_LABELS,
    STATUS_ICONS,
    STATUS_LABELS,
)

router = APIRouter(prefix="/admin", tags=["admin"])
Db = Annotated[Session, Depends(get_db)]

PAGE_SIZE = 50
LEADS_LIMIT = 200  # сколько последних заявок показывать (старые — SQL из docs/ANALYTICS.md)
FUNNEL_DAYS = 30  # за сколько дней показывать воронку (B12) над списком заказов

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# --- вход --------------------------------------------------------------------

# auto_error=False: без логина/пароля не отвечаем 401 сразу — сначала проверяем,
# включена ли админка вообще (иначе браузер спрашивал бы пароль у выключенной админки).
basic = HTTPBasic(auto_error=False)


def admin_enabled() -> bool:
    return bool(settings.admin_user and settings.admin_password)


def require_admin(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)],
) -> str:
    """Проверяет basic auth. Возвращает имя пользователя (для шаблонов)."""
    if not admin_enabled():
        raise HTTPException(
            status_code=503,
            detail="Админка выключена: задайте ADMIN_USER и ADMIN_PASSWORD в .env.",
        )
    ok = credentials is not None and (
        # compare_digest — сравнение за одинаковое время, чтобы пароль нельзя было
        # подбирать по скорости ответа.
        secrets.compare_digest(credentials.username.encode(), settings.admin_user.encode())
        & secrets.compare_digest(credentials.password.encode(), settings.admin_password.encode())
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Нужен логин и пароль админки.",
            headers={"WWW-Authenticate": 'Basic realm="TUC admin", charset="UTF-8"'},
        )
    # Защита от подделанной формы с чужого сайта (CSRF): браузер добавил бы наш пароль
    # и к ней. Современные браузеры присылают Sec-Fetch-Site; чужой сайт = cross-site.
    if request.method == "POST":
        site = request.headers.get("sec-fetch-site")
        if site not in (None, "same-origin", "none"):
            raise HTTPException(status_code=403, detail="Запрос с чужого сайта отклонён.")
    return credentials.username


Admin = Annotated[str, Depends(require_admin)]


# --- помощники для шаблонов ----------------------------------------------------


def fmt_money(amount: int | float | None) -> str:
    if amount is None:
        return ""
    return f"{int(round(amount)):,}".replace(",", " ") + " ₽"


def fmt_phone(phone: str) -> str:
    """«+79991234567» → «+7 999 123-45-67»; иностранный — как есть."""
    m = re.fullmatch(r"\+7(\d{3})(\d{3})(\d{2})(\d{2})", phone or "")
    return f"+7 {m[1]} {m[2]}-{m[3]}-{m[4]}" if m else phone


templates.env.filters["dt"] = fmt_dt
templates.env.filters["money"] = fmt_money
templates.env.filters["phone"] = fmt_phone
templates.env.filters["number"] = order_number  # {{ o.id|number }} → «BP-12»
templates.env.globals.update(
    STATUS_LABELS=STATUS_LABELS,
    STATUS_ICONS=STATUS_ICONS,
    NEXT_STATUSES=NEXT_STATUSES,
    ORDER_STATUSES=ORDER_STATUSES,
    DELIVERY_LABELS=DELIVERY_LABELS,
    POSTPROCESS_LABELS=POSTPROCESS_LABELS,
    site_url=lambda: settings.site_url,
)


def price_lines(quote: dict) -> list[tuple[str, str]]:
    """Разложение суммы заказа — те же строки, что видел клиент в расчёте."""
    lines = [
        (
            f"Пластик: {quote.get('material_g', 0):.0f} г × {quote.get('qty', 1)} шт"
            f" × {quote.get('price_per_g', 0)} ₽/г",
            fmt_money(quote.get("material_cost")),
        ),
        (
            f"Работа принтера: {(quote.get('print_time_s') or 0) / 3600:.1f} ч"
            f" × {quote.get('qty', 1)} шт × {quote.get('machine_rate', 0)} ₽/ч",
            fmt_money(quote.get("machine_cost")),
        ),
    ]
    if quote.get("k_supports", 1) != 1:
        lines.append((f"Поддержки: × {quote['k_supports']}", ""))
    if quote.get("k_batch", 1) != 1:
        lines.append((f"Скидка за тираж: × {quote['k_batch']}", ""))
    lines.append((f"Наценка: + {round(quote.get('margin', 0) * 100)} %", ""))
    lines.append(("Печать всего тиража", fmt_money(quote.get("print_subtotal"))))
    if quote.get("min_order_applied"):
        lines.append(("Минимальный заказ", fmt_money(quote.get("min_order"))))
    if quote.get("postprocess_cost"):
        lines.append(("Постобработка", fmt_money(quote["postprocess_cost"])))
    if quote.get("delivery_cost"):
        lines.append(("Доставка", fmt_money(quote["delivery_cost"])))
    lines.append(("Итого", fmt_money(quote.get("total"))))
    return lines


# --- выборка заказов -------------------------------------------------------------

STATUS_FILTERS = ("", "active", *ORDER_STATUSES)  # "" = все, active = есть работа


def orders_query(status: str, q: str):
    """SELECT по фильтрам списка. status: '' | active | один из ORDER_STATUSES."""
    stmt = select(Order)
    if status == "active":
        stmt = stmt.where(Order.status.in_(ACTIVE_STATUSES))
    elif status in ORDER_STATUSES:
        stmt = stmt.where(Order.status == status)

    q = (q or "").strip()
    if q:
        digits = re.sub(r"\D", "", q)
        conds = []
        number = parse_order_number(q)
        if number is not None:
            conds.append(Order.id == number)  # «12», «BP-12», «№12», старый «ТУЦ-12»
        if len(digits) >= 4:
            conds.append(Order.phone.like(f"%{digits}%"))  # хвост телефона
        like = f"%{q.lower()}%"
        conds += [
            func.lower(Order.customer_name).like(like),
            func.lower(func.coalesce(Order.email, "")).like(like),
            func.lower(func.coalesce(Order.original_name, "")).like(like),
            func.lower(func.coalesce(Order.company_name, "")).like(like),  # B33
            func.coalesce(Order.company_inn, "").like(like),
        ]
        stmt = stmt.where(or_(*conds))
    return stmt.order_by(Order.id.desc())


def list_params(status: str, q: str, page: int = 1) -> str:
    """Хвост ссылки с текущими фильтрами, чтобы страницы и CSV их не теряли."""
    params = {k: v for k, v in (("status", status), ("q", q)) if v}
    if page > 1:
        params["page"] = page
    return ("?" + urlencode(params)) if params else ""


def page_url(status: str, q: str, page: int) -> str:
    return "/admin/orders" + list_params(status, q, page)


# --- страницы ----------------------------------------------------------------


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
def admin_root(_: Admin) -> RedirectResponse:
    return RedirectResponse("/admin/orders", status_code=303)


@router.get("/orders", include_in_schema=False)
def orders_page(
    request: Request,
    user: Admin,
    db: Db,
    status: str = "",
    q: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
    ok: str = "",
    err: str = "",
):
    if status not in STATUS_FILTERS:
        status = ""
    stmt = orders_query(status, q)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    pages = max(1, -(-total // PAGE_SIZE))  # округление вверх
    page = min(page, pages)
    orders = list(db.scalars(stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)))
    counts = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())
    return templates.TemplateResponse(
        request,
        "admin/orders.html",
        {
            "user": user,
            "orders": orders,
            "paid_at": paid_at_by_order(db, orders),
            "status": status,
            "q": q,
            "page": page,
            "pages": pages,
            "total": total,
            "counts": counts,
            "active_count": sum(counts.get(s, 0) for s in ACTIVE_STATUSES),
            "funnel": (fn := funnel(db, days=FUNNEL_DAYS)),
            "funnel_pct": funnel_percents(fn),
            "funnel_days": FUNNEL_DAYS,
            "params": list_params(status, q),
            "prev_url": page_url(status, q, page - 1) if page > 1 else None,
            "next_url": page_url(status, q, page + 1) if page < pages else None,
            "ok": ok,
            "err": err,
        },
    )


_PLAIN_NUMBER = re.compile(r"^[+-][\d\s().-]*$")  # «+7 999 123-45-67», «-5» — просто число


def csv_safe(value: object) -> object:
    """Защита от формул в CSV: Excel выполняет ячейки, начинающиеся с «=», «+», «-», «@»
    (клиент может написать так имя или комментарий). Такие строки получают апостроф
    впереди — Excel покажет их как текст. Числа, телефоны вида «+7…» и пустые строки
    не трогаем. В Google-таблицу (app/sheets.py) значения идут как RAW — там формулы
    не выполняются."""
    if not isinstance(value, str) or not value:
        return value
    if value[0] in ("=", "@", "\t", "\r"):
        return "'" + value
    if value[0] in ("+", "-") and not _PLAIN_NUMBER.match(value):
        return "'" + value
    return value


@router.get("/orders.csv", include_in_schema=False)
def orders_csv(_: Admin, db: Db, status: str = "", q: str = "") -> Response:
    """Заказы по тем же фильтрам файлом CSV: разделитель «;», UTF-8 с BOM — Excel откроет сразу."""
    if status not in STATUS_FILTERS:
        status = ""
    orders = list(db.scalars(orders_query(status, q)))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(COLUMNS)  # те же колонки, что в Google-таблице (app/export.py)
    w.writerows([csv_safe(v) for v in row] for row in order_rows(db, orders))
    stamp = (datetime.now(UTC) + MSK).strftime("%Y-%m-%d")
    return Response(
        "﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="tuc-orders-{stamp}.csv"'},
    )


def _order_or_404(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Заказ № {order_id} не найден.")
    return order


def _upload_dir(order: Order) -> Path:
    return settings.data_dir / "uploads" / order.upload_id


def model_file(order: Order) -> Path | None:
    """Файл модели клиента: DATA_DIR/uploads/<id>/model.stl|3mf (если ещё на диске)."""
    for ext in ("stl", "3mf"):
        path = _upload_dir(order) / f"model.{ext}"
        if path.is_file():
            return path
    return None


def gcode_file(order: Order) -> Path | None:
    """G-code расчёта печати, по которому считалась цена (ключ лежит в снимке расчёта)."""
    key = (order.quote or {}).get("slice_key")
    if not key or not re.fullmatch(r"[A-Z0-9]+(_supports)?", key):
        return None
    path = _upload_dir(order) / "slices" / f"{key}.gcode"
    return path if path.is_file() else None


@router.get("/orders/{order_id}", include_in_schema=False)
def order_page(
    request: Request, user: Admin, db: Db, order_id: int, ok: str = "", err: str = ""
):
    order = _order_or_404(db, order_id)
    payments = list(
        db.scalars(select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc()))
    )
    return templates.TemplateResponse(
        request,
        "admin/order.html",
        {
            "user": user,
            "o": order,
            "payments": payments,
            "price_lines": price_lines(order.quote or {}),
            "has_model": model_file(order) is not None,
            "has_gcode": gcode_file(order) is not None,
            "ok": ok,
            "err": err,
        },
    )


@router.post("/orders/{order_id}/status", include_in_schema=False)
def set_status(_: Admin, db: Db, order_id: int, status: Annotated[str, Form()]) -> RedirectResponse:
    try:
        order = change_status(db, order_id, status)
        msg = {"ok": f"{order_number(order.id)}: статус «{STATUS_LABELS[order.status]}»."}
    except StatusError as e:
        msg = {"err": str(e)}
    return RedirectResponse(f"/admin/orders/{order_id}?{urlencode(msg)}", status_code=303)


@router.get("/orders/{order_id}/file", include_in_schema=False)
def download_model(_: Admin, db: Db, order_id: int) -> FileResponse:
    order = _order_or_404(db, order_id)
    path = model_file(order)
    if path is None:
        raise HTTPException(status_code=404, detail="Файла модели нет на диске.")
    name = Path(order.original_name or "").name or f"TUC-{order.id}.{path.suffix[1:]}"
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.get("/orders/{order_id}/gcode", include_in_schema=False)
def download_gcode(_: Admin, db: Db, order_id: int) -> FileResponse:
    order = _order_or_404(db, order_id)
    path = gcode_file(order)
    if path is None:
        raise HTTPException(status_code=404, detail="G-code для этого заказа не сохранён.")
    return FileResponse(
        path, filename=f"TUC-{order.id}_{path.stem}.gcode", media_type="text/plain"
    )


@router.get("/leads", include_in_schema=False)
def leads_page(request: Request, user: Admin, db: Db):
    """Заявки «цена по запросу» (B44). Здесь они видны, даже если Telegram не настроен."""
    leads = list(db.scalars(select(Lead).order_by(Lead.id.desc()).limit(LEADS_LIMIT)))
    total = db.scalar(select(func.count()).select_from(Lead)) or 0
    names = {key: m.name for key, m in materials.load_materials().items()}
    return templates.TemplateResponse(
        request,
        "admin/leads.html",
        {"user": user, "leads": leads, "total": total, "limit": LEADS_LIMIT, "names": names},
    )
