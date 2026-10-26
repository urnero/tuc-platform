"""Кабинет клиента (B32): вход по коду из письма, история заказов, повтор заказа.

Логина и пароля нет — клиент вводит e-mail, получает на него 6-значный код, вводит код.
Кабинет показывает все заказы, где `orders.email` совпадает с этим адресом (без учёта регистра),
включая те, что были оформлены до появления кабинета.

POST /api/v1/account/login            {email} → 202, письмо с кодом (LOGIN_CODE_TTL_MIN минут).
POST /api/v1/account/login/confirm    {email, code} → вход: cookie `tuc_session` на SESSION_DAYS.
GET  /api/v1/account                  кто вошёл + контакты из последнего заказа (для формы); 401.
GET  /api/v1/account/orders           заказы клиента, новые сверху; у каждого `can_repeat` —
                                      жив ли ещё файл модели (их удаляет app/cleanup.py).
POST /api/v1/account/logout           выход: строка сессии удаляется, cookie стирается.

Повтор заказа — на сайте: кнопка «Повторить» ведёт на страницу модели с теми же материалом,
тиражом и доставкой; цена считается заново по текущему прайсу (старая цена не повторяется).

Защита: код хранится как sha256, действует 15 минут, 5 попыток, один раз; запросы кода и
попытки входа — не больше RATE_LIMIT_LOGIN_PER_MIN в минуту с IP (app/limits.py) и не чаще
раза в минуту на адрес. Cookie HttpOnly + SameSite=Lax (+ Secure, если сайт на https).
Письмо шлёт app/mailer.py; без SMTP_HOST вход отвечает 503.
"""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.events import track
from app.limits import login_guard
from app.mailer import mail_enabled, send_mail
from app.models import ClientSession, LoginCode, Order
from app.orders import EMAIL_RE, payment_summary
from app.uploads import uploads_root

router = APIRouter(prefix="/api/v1/account", tags=["account"])
Db = Annotated[Session, Depends(get_db)]

COOKIE = "tuc_session"
CODE_RE = re.compile(r"^\d{6}$")
MAX_ATTEMPTS = 5  # неверных вводов на один код
RESEND_AFTER_S = 60  # новый код на тот же адрес — не чаще раза в минуту


def normalize_email(raw: str) -> str:
    """Адрес — ключ клиента: убираем пробелы, строчные буквы. Невалидный → 422."""
    email = (raw or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Проверьте e-mail.")
    return email


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(dt: datetime) -> datetime:
    """SQLite отдаёт даты без пояса — считаем их UTC (как и везде в проекте)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --- вход --------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str = Field(max_length=200)


class ConfirmRequest(BaseModel):
    email: str = Field(max_length=200)
    code: str = Field(max_length=16)


def code_letter(code: str) -> tuple[str, str]:
    """Тема и текст письма с кодом."""
    subject = f"{code} — код для входа в кабинет ТУЦ"
    text = (
        f"Код для входа в кабинет: {code}\n\n"
        f"Он действует {settings.login_code_ttl_min} минут. "
        "Если вы не запрашивали вход — просто не обращайте внимания на это письмо.\n\n"
        f"{settings.site_url}/account"
    )
    return subject, text


@router.post("/login", status_code=202, dependencies=[Depends(login_guard)])
def request_code(body: LoginRequest, db: Db) -> dict:
    if not mail_enabled():
        raise HTTPException(
            status_code=503,
            detail="Вход в кабинет пока недоступен: отправка писем не настроена.",
        )
    email = normalize_email(body.email)
    now = _now()
    # Старые коды этого адреса больше не нужны (просрочены или использованы).
    db.execute(
        delete(LoginCode).where(
            LoginCode.email == email,
            (LoginCode.expires_at < now) | (LoginCode.used_at.is_not(None)),
        )
    )
    last = db.scalar(
        select(LoginCode.created_at)
        .where(LoginCode.email == email)
        .order_by(LoginCode.id.desc())
        .limit(1)
    )
    if last is not None and (now - _as_utc(last)).total_seconds() < RESEND_AFTER_S:
        raise HTTPException(
            status_code=429,
            detail="Код уже отправлен. Проверьте почту или запросите новый через минуту.",
            headers={"Retry-After": str(RESEND_AFTER_S)},
        )
    code = f"{secrets.randbelow(10**6):06d}"
    ttl = timedelta(minutes=settings.login_code_ttl_min)
    db.add(LoginCode(email=email, code_hash=hash_code(code), expires_at=now + ttl))
    subject, text = code_letter(code)
    if not send_mail(email, subject, text):
        db.rollback()
        raise HTTPException(
            status_code=503, detail="Не удалось отправить письмо. Попробуйте позже."
        )
    db.commit()
    return {"sent": True, "email": email, "expires_in_min": settings.login_code_ttl_min}


@router.post("/login/confirm", dependencies=[Depends(login_guard)])
def confirm_code(body: ConfirmRequest, db: Db, response: Response) -> dict:
    email = normalize_email(body.email)
    code = re.sub(r"\s", "", body.code)
    if not CODE_RE.match(code):
        raise HTTPException(status_code=422, detail="Код — шесть цифр из письма.")
    now = _now()
    row = db.scalar(
        select(LoginCode)
        .where(LoginCode.email == email, LoginCode.used_at.is_(None))
        .order_by(LoginCode.id.desc())
        .limit(1)
    )
    if row is None or _as_utc(row.expires_at) < now:
        raise HTTPException(status_code=400, detail="Код не запрошен или устарел. Запросите новый.")
    if row.attempts >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=400, detail="Слишком много неверных попыток. Запросите новый код."
        )
    if not hmac.compare_digest(row.code_hash, hash_code(code)):
        row.attempts += 1
        db.commit()
        left = MAX_ATTEMPTS - row.attempts
        raise HTTPException(
            status_code=400,
            detail=f"Неверный код. Осталось попыток: {left}."
            if left
            else "Неверный код. Запросите новый.",
        )
    row.used_at = now
    session = ClientSession(
        token=secrets.token_hex(16),
        email=email,
        expires_at=now + timedelta(days=settings.session_days),
    )
    db.add(session)
    # Просроченные сессии этого адреса убираем заодно — таблица не растёт.
    db.execute(
        delete(ClientSession).where(ClientSession.email == email, ClientSession.expires_at < now)
    )
    track("account_login", db=db, props={})
    db.commit()
    set_session_cookie(response, session.token)
    return account_info(db, email)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.site_url.startswith("https://"),
        path="/",
    )


# --- кто вошёл ---------------------------------------------------------------


def current_email(request: Request, db: Db) -> str | None:
    """E-mail клиента из cookie `tuc_session`, если сессия есть и не истекла. Иначе None.
    Зависимость для ручек, которым вход не обязателен (форма заказа)."""
    token = request.cookies.get(COOKIE, "")
    if not re.match(r"^[0-9a-f]{32}$", token):
        return None
    session = db.scalar(select(ClientSession).where(ClientSession.token == token))
    if session is None or _as_utc(session.expires_at) < _now():
        return None
    return session.email


CurrentEmail = Annotated[str | None, Depends(current_email)]


def require_email(email: CurrentEmail) -> str:
    """Зависимость для ручек кабинета: без входа — 401."""
    if email is None:
        raise HTTPException(status_code=401, detail="Войдите в кабинет.")
    return email


Email = Annotated[str, Depends(require_email)]


def client_orders(db: Session, email: str) -> list[Order]:
    """Заказы клиента, новые сверху: по e-mail без учёта регистра."""
    q = select(Order).where(func.lower(Order.email) == email).order_by(Order.id.desc())
    return list(db.scalars(q))


def account_info(db: Session, email: str) -> dict:
    """Ответ GET /account: адрес, сколько заказов, контакты из последнего заказа
    (сайт подставляет их в форму нового заказа)."""
    last = db.scalar(
        select(Order).where(func.lower(Order.email) == email).order_by(Order.id.desc()).limit(1)
    )
    count = db.scalar(select(func.count(Order.id)).where(func.lower(Order.email) == email)) or 0
    contacts = (
        {"name": last.customer_name, "phone": last.phone, "address": last.address or ""}
        if last
        else None
    )
    return {"email": email, "orders_count": int(count), "contacts": contacts}


@router.get("")
def get_account(email: Email, db: Db) -> dict:
    return account_info(db, email)


def upload_available(upload_id: str) -> bool:
    """Файл модели ещё лежит в DATA_DIR (cleanup удаляет папки старых заказов целиком)."""
    return (uploads_root() / upload_id / "meta.json").is_file()


@router.get("/orders")
def get_orders(email: Email, db: Db) -> dict:
    rows = []
    for order in client_orders(db, email):
        extra = {
            "payment": payment_summary(db, order),
            "can_repeat": upload_available(order.upload_id),
        }
        rows.append(order.to_dict() | extra)
    return {"orders": rows}


@router.post("/logout")
def logout(request: Request, db: Db, response: Response) -> dict:
    token = request.cookies.get(COOKIE, "")
    if token:
        db.execute(delete(ClientSession).where(ClientSession.token == token))
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
