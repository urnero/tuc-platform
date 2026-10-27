"""Отправка писем клиентам: код для входа в кабинет (B32), статусы заказа (B34, `app/notify.py`).

Настройки в .env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_SSL.
Подойдёт любая почта с SMTP: Яндекс 360, Mail.ru, Timeweb, свой сервер.

Три режима:
- SMTP_HOST пустой — писем нет, `send_mail()` возвращает False (кабинет отвечает 503);
- SMTP_HOST=log — письмо пишется в лог api вместо отправки (разработка без почты:
  код для входа виден в `docker compose logs api`);
- иначе — обычная отправка через smtplib. Ошибка SMTP не роняет API: пишем в лог, False.

Только текст, без HTML: письма короткие (код, ссылка), а текст не попадает в спам из-за вёрстки.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger(__name__)

LOG_MODE = "log"


def mail_enabled() -> bool:
    return bool(settings.smtp_host)


def build_message(to: str, subject: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    return msg


def send_mail(to: str, subject: str, text: str) -> bool:
    """Отправить письмо. True — ушло (или записано в лог в режиме log), False — не отправлено."""
    if not mail_enabled():
        log.warning("SMTP_HOST не задан — письмо «%s» для %s не отправлено", subject, to)
        return False
    msg = build_message(to, subject, text)
    if settings.smtp_host == LOG_MODE:
        log.info("Письмо (режим log) для %s · %s\n%s", to, subject, text)
        return True
    try:
        _deliver(msg)
    except (smtplib.SMTPException, OSError) as e:
        log.error("Письмо «%s» для %s не отправлено: %s", subject, to, e)
        return False
    return True


def _deliver(msg: EmailMessage) -> None:
    """Собственно SMTP: 465 с TLS сразу (SMTP_SSL=true) или 587 со STARTTLS."""
    if settings.smtp_ssl:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        server.starttls()
    with server:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
