"""Экспорт заказов в Google-таблицу учёта «Учет 3D-печати ТУЦ» (B11; имя таблицы у владельца).

Postgres — источник истины (DECISIONS.md). Таблица получает копию: раз в ночь worker
(cron в `app/worker.py`) переписывает лист `GOOGLE_SHEET_TAB` целиком — первая строка заголовок,
дальше по строке на заказ, колонки те же, что в CSV админки (`app/export.py`). Остальные листы
таблицы не трогаем: владелец строит на них свои формулы и сводные, ссылаясь на этот лист.

B47 — живой лог: при создании заказа и при каждой смене статуса (бот, админка, оплата ЮKassa)
строка этого заказа сразу появляется или обновляется на том же листе — `push_order(order_id)`.
Строку ищем по id заказа в колонке A; нет такой — дописываем в конец. Делается в фоновом
потоке (клиент и бот не ждут Google), до 3 попыток; не вышло — пишем в лог, а ночная
выгрузка всё равно перепишет лист целиком (самопроверка). Выключить живой лог, оставив
ночную выгрузку: `GOOGLE_SHEET_LIVE=false`.

Запустить руками: `python -m app.sheets` (в Docker: `docker compose exec api python -m app.sheets`).

Google: сервисный аккаунт (JSON-ключ в `GOOGLE_SA_JSON_PATH`), которому таблица расшарена
как редактору; id таблицы — из её адреса (`GOOGLE_SHEET_ID`). Пусто = экспорт выключен.
Ходим в Sheets API v4 напрямую через httpx (как в ЮKassa), без gspread: три вызова —
список листов, очистить лист, записать значения. Токен доступа получаем по JWT сервисного
аккаунта (RS256, PyJWT) — так делает и сама библиотека Google.
"""

import json
import logging
import sys
import threading
import time
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_factory
from app.export import COLUMNS, MSK, all_orders, order_rows
from app.models import Order

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_URL = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TRANSPORT: httpx.BaseTransport | None = None  # тесты подставляют поддельный Google
IN_BACKGROUND = True  # тесты выключают, чтобы запись шла в том же потоке
RETRY_DELAYS_S = (5, 30)  # паузы между 3 попытками живого лога; тесты ставят ()
# Одна запись за раз в пределах процесса: иначе «создан» и «оплачен» одного заказа,
# пришедшие почти одновременно, оба не нашли бы строку и дописали её дважды.
_PUSH_LOCK = threading.Lock()


class SheetsError(RuntimeError):
    """Экспорт не удался: нет ключа, Google ответил ошибкой, таблица не расшарена и т. п."""


def enabled() -> bool:
    return bool(settings.google_sa_json_path and settings.google_sheet_id)


def _client() -> httpx.Client:
    return httpx.Client(timeout=60, transport=TRANSPORT)


# --- доступ --------------------------------------------------------------------


def load_service_account() -> dict:
    """JSON-ключ сервисного аккаунта: client_email, private_key, token_uri."""
    try:
        data = json.loads(settings.google_sa_json_path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise SheetsError(
            f"Нет файла ключа GOOGLE_SA_JSON_PATH={settings.google_sa_json_path}"
        ) from e
    except (OSError, ValueError) as e:
        raise SheetsError(f"Не читается ключ сервисного аккаунта: {e}") from e
    for key in ("client_email", "private_key"):
        if not data.get(key):
            raise SheetsError(f"В ключе сервисного аккаунта нет поля {key}.")
    return data


def access_token(client: httpx.Client, sa: dict, scope: str = SCOPE) -> str:
    """OAuth2-токен на час: подписываем JWT ключом сервисного аккаунта и меняем на токен.
    `scope` — к чему доступ: таблицы (по умолчанию) или Диск (app/drive.py, B46)."""
    now = int(time.time())
    token_url = sa.get("token_uri") or TOKEN_URL
    claims = {
        "iss": sa["client_email"], "scope": scope, "aud": token_url, "iat": now, "exp": now + 3600,
    }
    assertion = jwt.encode(claims, sa["private_key"], algorithm="RS256")
    r = client.post(
        token_url,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
    )
    if r.status_code != 200:
        raise SheetsError(f"Google не выдал токен ({r.status_code}): {r.text[:300]}")
    return r.json()["access_token"]


# --- таблица ---------------------------------------------------------------------


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code == 403:
        raise SheetsError(
            f"{what}: доступ запрещён. Расшарьте таблицу редактору "
            "(e-mail сервисного аккаунта из JSON-ключа)."
        )
    if r.status_code == 404:
        raise SheetsError(f"{what}: таблица не найдена — проверьте GOOGLE_SHEET_ID.")
    if r.status_code >= 400:
        raise SheetsError(f"{what}: Google ответил {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def ensure_tab(client: httpx.Client, headers: dict, tab: str) -> str:
    """Лист с именем tab должен быть; если нет — создаём. Возвращает ссылку на таблицу."""
    base = f"{SHEETS_URL}/{settings.google_sheet_id}"
    fields = {"fields": "spreadsheetUrl,sheets.properties.title"}
    meta = _check(client.get(base, params=fields, headers=headers), "Чтение таблицы")
    titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if tab not in titles:
        _check(
            client.post(
                f"{base}:batchUpdate",
                json={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
                headers=headers,
            ),
            f"Создание листа «{tab}»",
        )
    return meta.get("spreadsheetUrl", "")


def write_rows(client: httpx.Client, headers: dict, tab: str, rows: list[list]) -> None:
    """Очистить лист и записать строки с A1. RAW — значения как есть (телефон остаётся текстом)."""
    base = f"{SHEETS_URL}/{settings.google_sheet_id}/values"
    rng = _quoted(tab)  # имя листа в кавычках — в нём пробелы и скобки
    _check(client.post(f"{base}/{rng}:clear", headers=headers), f"Очистка листа «{tab}»")
    _check(
        client.put(
            f"{base}/{rng}",
            params={"valueInputOption": "RAW"},
            json={"range": f"'{tab}'", "majorDimension": "ROWS", "values": rows},
            headers=headers,
        ),
        f"Запись в лист «{tab}»",
    )


def export_orders(db: Session) -> dict:
    """Переписать лист заказов в Google-таблице. Возвращает {rows, tab, url, exported_at}."""
    if not enabled():
        raise SheetsError("Экспорт выключен: задайте GOOGLE_SA_JSON_PATH и GOOGLE_SHEET_ID в .env.")
    tab = settings.google_sheet_tab
    rows = [COLUMNS, *order_rows(db, all_orders(db))]
    with _client() as client:
        headers = {"Authorization": f"Bearer {access_token(client, load_service_account())}"}
        url = ensure_tab(client, headers, tab)
        write_rows(client, headers, tab, rows)
    exported_at = (datetime.now(UTC) + MSK).strftime("%d.%m.%Y %H:%M")
    result = {"rows": len(rows) - 1, "tab": tab, "url": url, "exported_at": exported_at}
    log.info("Google-таблица: выгружено %s заказов в лист «%s»", result["rows"], tab)
    return result


# --- живой лог (B47) -------------------------------------------------------------


def _quoted(tab: str) -> str:
    return quote(f"'{tab}'", safe="")


def find_row(
    client: httpx.Client, headers: dict, tab: str, order_id: int
) -> tuple[int | None, int]:
    """Номер строки (с 1) с этим id в колонке A и сколько строк в колонке A всего.
    Значения Google отдаёт текстом («12»), поэтому сравниваем строки."""
    rng = quote(f"'{tab}'!A:A", safe="")
    data = _check(
        client.get(f"{SHEETS_URL}/{settings.google_sheet_id}/values/{rng}", headers=headers),
        f"Чтение листа «{tab}»",
    )
    column = [row[0] if row else "" for row in data.get("values", [])]
    for i, value in enumerate(column, start=1):
        if i > 1 and str(value).strip() == str(order_id):
            return i, len(column)
    return None, len(column)


def upsert_row(client: httpx.Client, headers: dict, tab: str, order_id: int, row: list) -> str:
    """Обновить строку заказа или дописать её в конец. → «updated» / «appended»."""
    base = f"{SHEETS_URL}/{settings.google_sheet_id}/values"
    found, used = find_row(client, headers, tab, order_id)
    if found is not None:
        rng = quote(f"'{tab}'!A{found}", safe="")
        _check(
            client.put(
                f"{base}/{rng}",
                params={"valueInputOption": "RAW"},
                json={"range": f"'{tab}'!A{found}", "majorDimension": "ROWS", "values": [row]},
                headers=headers,
            ),
            f"Обновление строки в листе «{tab}»",
        )
        return "updated"
    rows = [row] if used else [COLUMNS, row]  # пустой лист — сначала заголовок
    _check(
        client.post(
            f"{base}/{_quoted(tab)}:append",
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            json={"majorDimension": "ROWS", "values": rows},
            headers=headers,
        ),
        f"Добавление строки в лист «{tab}»",
    )
    return "appended"


def sync_order(db: Session, order_id: int) -> str | None:
    """Строка одного заказа → лист. None — живой лог выключен или заказа нет."""
    if not (enabled() and settings.google_sheet_live):
        return None
    order = db.get(Order, order_id)
    if order is None:
        return None
    row = order_rows(db, [order])[0]
    tab = settings.google_sheet_tab
    with _PUSH_LOCK, _client() as client:
        headers = {"Authorization": f"Bearer {access_token(client, load_service_account())}"}
        ensure_tab(client, headers, tab)
        result = upsert_row(client, headers, tab, order_id, row)
    log.info("Google-таблица: заказ %s — %s", order_id, result)
    return result


def sync_order_job(order_id: int) -> str | None:
    """Своя сессия БД и до 3 попыток. Ошибку не пробрасываем: заказ уже оформлен,
    а ночная выгрузка всё равно перепишет лист."""
    delays = (*RETRY_DELAYS_S, None)
    for attempt, delay in enumerate(delays, start=1):
        try:
            with session_factory()() as db:
                return sync_order(db, order_id)
        except (SheetsError, httpx.HTTPError) as e:
            log.warning("Google-таблица: заказ %s, попытка %s: %s", order_id, attempt, e)
            if delay is None:
                return "failed"
            time.sleep(delay)
    return "failed"


def push_order(order_id: int) -> None:
    """Заказ создан или сменил статус — обновить его строку в таблице (в фоне).
    Без ключей Google или с GOOGLE_SHEET_LIVE=false — ничего не делаем."""
    if not (enabled() and settings.google_sheet_live):
        return
    if not IN_BACKGROUND:
        sync_order_job(order_id)
        return
    threading.Thread(
        target=sync_order_job, args=(order_id,), daemon=True, name="sheet-order"
    ).start()


def export_orders_job() -> dict | None:
    """Для cron в worker и CLI: своя сессия БД; без ключей — пропуск, а не ошибка."""
    if not enabled():
        log.info("Google-таблица: экспорт выключен (нет GOOGLE_SA_JSON_PATH / GOOGLE_SHEET_ID)")
        return None
    with session_factory()() as db:
        return export_orders(db)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = export_orders_job()
    except SheetsError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    if result is None:
        print("Экспорт выключен: задайте GOOGLE_SA_JSON_PATH и GOOGLE_SHEET_ID в .env.")
        return 0
    print(f"Готово: {result['rows']} заказов → лист «{result['tab']}» {result['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
