"""Файлы заказов в Google Drive (B46).

Заказ оформлен → в фоне (клиент не ждёт) создаём папку
`Заказы сайта/<ГГГГ-ММ>/<BP-N> — <имя клиента>/` и кладём туда:
- модель из заказа (если её раскрасили или нанесли надпись — это уже обработанный 3MF/STL);
- исходник, из которого её сделали (если был: тиснение B30, раскраска B31);
- `заказ.txt` — что печатать: материал, тираж, поддержки, постобработка, сумма, комментарий
  (без телефона и e-mail — они в админке и таблице учёта).
Ссылка на папку → `orders.drive_folder_url`, в Google-таблицу (колонка `drive_folder_url`),
в админку и отдельным сообщением владельцу в Telegram («📁 Файлы BP-N в Drive»).

Как и живой лог таблицы (app/sheets.py, B47): фоновый поток, до 3 попыток, дальше только
лог. Ночью worker (cron `drive_backfill`, 05:20 МСК) докопирует заказы за последние
30 дней, у которых папки ещё нет — так чинится всё, что не дошло днём. Повтор безопасен:
папки ищем по имени, файл с тем же именем второй раз не загружаем.

Доступ (выбирается сам по тому, что задано в .env):
- OAuth от имени владельца (обычный Gmail): GOOGLE_DRIVE_CLIENT_ID / _CLIENT_SECRET /
  _REFRESH_TOKEN. Права только `drive.file` — приложение видит лишь то, что само создало,
  поэтому корневую папку «Заказы сайта» оно создаёт в «Моём диске» само. Токен получить
  один раз на ноутбуке: `python -m app.drive auth`.
- Сервисный аккаунт (Google Workspace): GOOGLE_SA_JSON_PATH + GOOGLE_DRIVE_FOLDER_ID —
  папка на общем диске, где аккаунт — редактор. В обычный «Мой диск» сервисный аккаунт
  файлы класть не может: у него нет своего места (Google отвечает storageQuotaExceeded).
Ничего не задано — копирование выключено, всё остальное работает.

Руками: `python -m app.drive check` — проверить доступ; `python -m app.drive 12` — скопировать
заказ 12 ещё раз (в Docker: `docker compose exec api python -m app.drive 12`).
Ходим в Drive API v3 напрямую через httpx, как в app/sheets.py.
"""

import json
import logging
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sheets
from app.config import settings
from app.db import session_factory
from app.export import MSK, fmt_dt
from app.models import Order

log = logging.getLogger(__name__)

FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE_OAUTH = "https://www.googleapis.com/auth/drive.file"  # только свои файлы приложения
SCOPE_SA = "https://www.googleapis.com/auth/drive"  # SA видит общий диск, куда его добавили
FOLDER_MIME = "application/vnd.google-apps.folder"
# Общие диски (Workspace) Google отдаёт только с этими параметрами; для «Моего диска» не мешают.
ALL_DRIVES = {"supportsAllDrives": "true"}
TRANSPORT: httpx.BaseTransport | None = None  # тесты подставляют поддельный Google
IN_BACKGROUND = True  # тесты выключают, чтобы копирование шло в том же потоке
RETRY_DELAYS_S = (10, 60)  # паузы между 3 попытками; тесты ставят ()
BACKFILL_DAYS = 30  # ночью докопируем заказы не старше этого
BACKFILL_LIMIT = 50  # и не больше стольких за ночь
_LOCK = threading.Lock()  # один заказ за раз в процессе: иначе две папки с одним именем


class DriveError(RuntimeError):
    """Копирование не удалось: нет доступа, нет папки, Google ответил ошибкой."""


def mode() -> str | None:
    """«oauth» — от имени владельца, «sa» — сервисный аккаунт, None — выключено."""
    if (
        settings.google_drive_client_id
        and settings.google_drive_client_secret
        and settings.google_drive_refresh_token
    ):
        return "oauth"
    if settings.google_sa_json_path and settings.google_drive_folder_id:
        return "sa"
    return None


def enabled() -> bool:
    return mode() is not None


def _client() -> httpx.Client:
    return httpx.Client(timeout=120, transport=TRANSPORT)


def access_token(client: httpx.Client) -> str:
    if mode() == "sa":
        try:
            sa = sheets.load_service_account()
            return sheets.access_token(client, sa, scope=SCOPE_SA)
        except sheets.SheetsError as e:
            raise DriveError(str(e)) from e
    r = client.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": settings.google_drive_client_id,
            "client_secret": settings.google_drive_client_secret,
            "refresh_token": settings.google_drive_refresh_token,
        },
    )
    if r.status_code != 200:
        # invalid_grant — токен отозван или истёк (приложение в режиме Testing живёт 7 дней).
        raise DriveError(
            f"Google не выдал токен Drive ({r.status_code}): {r.text[:300]}. "
            "Получите новый: python -m app.drive auth"
        )
    return r.json()["access_token"]


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code == 403 and "storageQuotaExceeded" in r.text:
        raise DriveError(
            f"{what}: у сервисного аккаунта нет места на Диске. Нужна папка на общем диске "
            "(Workspace) или OAuth владельца — docs/DEPLOY.md, «Google Drive»."
        )
    if r.status_code in (403, 404) and settings.google_drive_folder_id:
        raise DriveError(
            f"{what}: Google ответил {r.status_code}. Проверьте GOOGLE_DRIVE_FOLDER_ID и что "
            "папка расшарена редактору (e-mail сервисного аккаунта)."
        )
    if r.status_code >= 400:
        raise DriveError(f"{what}: Google ответил {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def _q(value: str) -> str:
    """Строка внутри запроса поиска Drive: экранируем \\ и '."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_folder(client: httpx.Client, headers: dict, name: str, parent: str) -> dict | None:
    q = (
        f"name = '{_q(name)}' and '{_q(parent)}' in parents "
        f"and mimeType = '{FOLDER_MIME}' and trashed = false"
    )
    params = {
        "q": q, "fields": "files(id,webViewLink)", "pageSize": "1",
        "includeItemsFromAllDrives": "true", **ALL_DRIVES,
    }
    files = _check(client.get(FILES_URL, params=params, headers=headers), "Поиск папки")
    found = files.get("files") or []
    return found[0] if found else None


def ensure_folder(client: httpx.Client, headers: dict, name: str, parent: str) -> dict:
    """Папка name внутри parent: есть — берём, нет — создаём. → {id, webViewLink}."""
    folder = find_folder(client, headers, name, parent)
    if folder:
        return folder
    return _check(
        client.post(
            FILES_URL,
            params={"fields": "id,webViewLink", **ALL_DRIVES},
            json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]},
            headers=headers,
        ),
        f"Создание папки «{name}»",
    )


def file_names(client: httpx.Client, headers: dict, folder_id: str) -> set[str]:
    params = {
        "q": f"'{_q(folder_id)}' in parents and trashed = false",
        "fields": "files(name)", "pageSize": "100",
        "includeItemsFromAllDrives": "true", **ALL_DRIVES,
    }
    files = _check(client.get(FILES_URL, params=params, headers=headers), "Список файлов")
    return {f["name"] for f in files.get("files") or []}


def upload(client: httpx.Client, headers: dict, folder_id: str, name: str, data: bytes) -> None:
    """Загрузка «resumable»: сначала описание файла → адрес для загрузки, потом сами байты.
    Так проходят и файлы по 100 МБ (простая multipart-загрузка — только до 5 МБ)."""
    start = client.post(
        f"{UPLOAD_URL}?{urlencode({'uploadType': 'resumable', **ALL_DRIVES})}",
        json={"name": name, "parents": [folder_id]},
        headers={**headers, "X-Upload-Content-Type": "application/octet-stream"},
    )
    _check(start, f"Загрузка «{name}»")
    location = start.headers.get("location")
    if not location:
        raise DriveError(f"Загрузка «{name}»: Google не дал адрес для загрузки.")
    put = client.put(
        location, content=data,
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    _check(put, f"Загрузка «{name}»")


# --- что копируем ------------------------------------------------------------------


def _clean(name: str, limit: int = 120) -> str:
    """Имя для Drive: без / и переводов строк, не длиннее limit."""
    bad = "/\\\n\r\t"
    return "".join("_" if ch in bad else ch for ch in name).strip()[:limit] or "файл"


def month_name(order: Order) -> str:
    created = order.created_at or datetime.now(UTC)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (created.astimezone(UTC) + MSK).strftime("%Y-%m")


def folder_name(order: Order) -> str:
    from app.orders import order_number

    return _clean(f"{order_number(order.id)} — {order.customer_name}")


def _upload_model(upload_id: str) -> tuple[Path, dict] | None:
    """Файл модели загрузки и её meta.json; None — папки уже нет (удалена по сроку)."""
    from app.uploads import ID_RE, uploads_root

    if not ID_RE.match(upload_id or ""):
        return None
    folder = uploads_root() / upload_id
    try:
        meta = json.loads((folder / "meta.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    path = folder / f"model.{meta.get('ext', 'stl')}"
    return (path, meta) if path.is_file() else None


def order_text(order: Order) -> str:
    """«заказ.txt»: что печатать. Без телефона и e-mail клиента."""
    from app.orders import order_number
    from app.telegram import DELIVERY_LABELS, POSTPROCESS_LABELS, admin_order_url

    quote = order.quote or {}
    lines = [
        f"Заказ {order_number(order.id)} от {fmt_dt(order.created_at)} МСК",
        f"Клиент: {order.customer_name}",
        f"Материал: {order.material}" + (f" ({quote['tech']})" if quote.get("tech") else ""),
        f"Тираж: {order.qty} шт",
        f"Поддержки: {'да' if order.supports else 'нет'}",
        f"Постобработка: {POSTPROCESS_LABELS.get(order.postprocess, order.postprocess)}",
        f"Доставка: {DELIVERY_LABELS.get(order.delivery, order.delivery)}",
        f"Сумма: {order.total} ₽",
    ]
    if quote.get("print_time_s") or quote.get("material_g"):
        hours = (quote.get("print_time_s") or 0) / 3600 * order.qty
        grams = (quote.get("material_g") or 0) * order.qty
        lines.append(f"Печать: ~{hours:.1f} ч, {grams:.0f} г на весь тираж")
    if quote.get("decor"):
        lines.append(f"Оформление: {quote['decor']}")
    if order.original_name:
        lines.append(f"Файл: {order.original_name}")
    if order.comment:
        lines.append(f"Комментарий клиента: {order.comment}")
    lines.append(f"Админка: {admin_order_url(order.id)}")
    return "\n".join(lines) + "\n"


def order_files(order: Order) -> list[tuple[str, bytes]]:
    """[(имя в Drive, содержимое)]: модель заказа, её исходник (если был), заказ.txt."""
    files: list[tuple[str, bytes]] = []
    model = _upload_model(order.upload_id)
    if model is not None:
        path, meta = model
        files.append((_clean(meta.get("original_name") or path.name), path.read_bytes()))
        # Тиснение/раскраска хранят исходную загрузку в meta["emboss"|"paint"]["parent_id"].
        parent_id = (meta.get(meta.get("source") or "") or {}).get("parent_id")
        parent = _upload_model(parent_id) if parent_id else None
        if parent is not None:
            p_path, p_meta = parent
            name = p_meta.get("original_name") or p_path.name
            files.append((_clean(f"исходник — {name}"), p_path.read_bytes()))
    files.append(("заказ.txt", order_text(order).encode("utf-8")))
    return files


# --- копирование ---------------------------------------------------------------------


def root_folder(client: httpx.Client, headers: dict) -> str:
    """Куда класть месяцы: заданная папка (общий диск) или своя «Заказы сайта» в «Моём диске»."""
    if settings.google_drive_folder_id:
        return settings.google_drive_folder_id
    return ensure_folder(client, headers, settings.google_drive_root_name, "root")["id"]


def copy_order(db: Session, order_id: int, tell_owner: bool = True) -> str | None:
    """Скопировать файлы заказа в Drive. → ссылка на папку; None — выключено/нечего копировать."""
    if not enabled():
        return None
    order = db.get(Order, order_id)
    if order is None or order.anonymized_at is not None:
        return None
    files = order_files(order)
    with _LOCK, _client() as client:
        headers = {"Authorization": f"Bearer {access_token(client)}"}
        month = ensure_folder(client, headers, month_name(order), root_folder(client, headers))
        folder = ensure_folder(client, headers, folder_name(order), month["id"])
        have = file_names(client, headers, folder["id"])
        for name, data in files:
            if name not in have:
                upload(client, headers, folder["id"], name, data)
    url = folder.get("webViewLink") or f"https://drive.google.com/drive/folders/{folder['id']}"
    first_time = order.drive_folder_url is None
    order.drive_folder_url = url
    db.commit()
    log.info("Google Drive: заказ %s — %s файл(ов) в %s", order_id, len(files), url)
    if first_time:
        sheets.push_order(order_id)  # колонка drive_folder_url в таблице учёта
        if tell_owner:
            _tell_owner(order, url)
    return url


def _tell_owner(order: Order, url: str) -> None:
    from app import telegram as tg
    from app.orders import order_number

    if not tg.telegram_enabled():
        return
    text = f'📁 Файлы {order_number(order.id)} в Google Drive: <a href="{tg.esc(url)}">папка</a>'
    tg.send_message(settings.telegram_owner_chat_id, text)


def copy_order_job(order_id: int) -> str | None:
    """Своя сессия БД и до 3 попыток. Ошибку не пробрасываем: заказ уже оформлен,
    а ночная задача докопирует."""
    delays = (*RETRY_DELAYS_S, None)
    for attempt, delay in enumerate(delays, start=1):
        try:
            with session_factory()() as db:
                return copy_order(db, order_id)
        except (DriveError, httpx.HTTPError, OSError) as e:
            log.warning("Google Drive: заказ %s, попытка %s: %s", order_id, attempt, e)
            if delay is None:
                return "failed"
            time.sleep(delay)
    return "failed"


def push_order(order_id: int) -> None:
    """Заказ создан — скопировать его файлы (в фоне). Drive выключен — ничего не делаем."""
    if not enabled():
        return
    if not IN_BACKGROUND:
        copy_order_job(order_id)
        return
    threading.Thread(
        target=copy_order_job, args=(order_id,), daemon=True, name="drive-order"
    ).start()


def backfill_job() -> dict | None:
    """Ночью (cron в worker): заказы последних 30 дней без папки — скопировать.
    Отменённые и обезличенные пропускаем. Владельцу в Telegram не пишем — ссылка в таблице."""
    if not enabled():
        log.info("Google Drive: выключено (нет доступа в .env)")
        return None
    since = datetime.now(UTC) - timedelta(days=BACKFILL_DAYS)
    copied, failed = 0, 0
    with session_factory()() as db:
        ids = db.scalars(
            select(Order.id)
            .where(
                Order.drive_folder_url.is_(None),
                Order.anonymized_at.is_(None),
                Order.status != "cancelled",
                Order.created_at >= since,
            )
            .order_by(Order.id)
            .limit(BACKFILL_LIMIT)
        ).all()
        for order_id in ids:
            try:
                if copy_order(db, order_id, tell_owner=False):
                    copied += 1
            except (DriveError, httpx.HTTPError, OSError) as e:
                failed += 1
                db.rollback()
                log.warning("Google Drive: ночью заказ %s не скопирован: %s", order_id, e)
    log.info("Google Drive: ночью скопировано %s, ошибок %s", copied, failed)
    return {"copied": copied, "failed": failed}


# --- командная строка --------------------------------------------------------------------


def auth_cli() -> int:
    """Один раз на ноутбуке: открыть вход Google, получить refresh-токен для .env.

    Нужен OAuth-клиент типа «Desktop app» (docs/DEPLOY.md). Google вернёт браузер на
    http://127.0.0.1:<порт> — этот скрипт ловит ответ и меняет код на токен."""
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    client_id = settings.google_drive_client_id or input("Client ID: ").strip()
    secret = settings.google_drive_client_secret or input("Client secret: ").strip()
    got: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — имя задано http.server
            got.update({k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Готово, вернитесь в терминал.".encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE_OAUTH, "access_type": "offline", "prompt": "consent",
    })
    print("Откройте в браузере и войдите тем Google-аккаунтом, на чей Диск класть заказы:")
    print(url)
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        server.handle_request()
    if "error" in got:
        print(f"Google отказал: {got['error']}", file=sys.stderr)
        return 1
    with _client() as client:
        r = client.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": got["code"], "client_id": client_id,
            "client_secret": secret, "redirect_uri": redirect,
        })
    if r.status_code != 200 or "refresh_token" not in r.json():
        print(f"Ошибка обмена кода ({r.status_code}): {r.text[:300]}", file=sys.stderr)
        return 1
    print("\nВпишите в /srv/tuc/<стенд>/.env и выполните docker compose up -d api worker:")
    print(f"GOOGLE_DRIVE_CLIENT_ID={client_id}")
    print(f"GOOGLE_DRIVE_CLIENT_SECRET={secret}")
    print(f"GOOGLE_DRIVE_REFRESH_TOKEN={r.json()['refresh_token']}")
    return 0


def check_cli() -> int:
    """Проверить доступ: получить токен и найти/создать корневую папку."""
    if not enabled():
        print("Drive выключен: задайте GOOGLE_DRIVE_* в .env (docs/DEPLOY.md, «Google Drive»).")
        return 0
    with _client() as client:
        headers = {"Authorization": f"Bearer {access_token(client)}"}
        root = root_folder(client, headers)
    print(f"Доступ есть ({mode()}): https://drive.google.com/drive/folders/{root}")
    return 0


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cmd = argv[0] if argv else "check"
    try:
        if cmd == "auth":
            return auth_cli()
        if cmd == "check":
            return check_cli()
        if cmd.isdigit():
            with session_factory()() as db:
                url = copy_order(db, int(cmd), tell_owner=False)
            print(url or "Нечего копировать: Drive выключен, заказа нет или он обезличен.")
            return 0
    except (DriveError, httpx.HTTPError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    print("Команды: python -m app.drive [check | auth | <номер заказа>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
