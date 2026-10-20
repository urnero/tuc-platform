"""Экспорт заказов в Google-таблицу учёта «Учет 3D-печати ТУЦ» (B11).

Postgres — источник истины (DECISIONS.md). Таблица получает копию: раз в ночь worker
(cron в `app/worker.py`) переписывает лист `GOOGLE_SHEET_TAB` целиком — первая строка заголовок,
дальше по строке на заказ, колонки те же, что в CSV админки (`app/export.py`). Остальные листы
таблицы не трогаем: владелец строит на них свои формулы и сводные, ссылаясь на этот лист.

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
import time
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_factory
from app.export import COLUMNS, MSK, all_orders, order_rows

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_URL = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TRANSPORT: httpx.BaseTransport | None = None  # тесты подставляют поддельный Google


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


def access_token(client: httpx.Client, sa: dict) -> str:
    """OAuth2-токен на час: подписываем JWT ключом сервисного аккаунта и меняем на токен."""
    now = int(time.time())
    token_url = sa.get("token_uri") or TOKEN_URL
    claims = {
        "iss": sa["client_email"], "scope": SCOPE, "aud": token_url, "iat": now, "exp": now + 3600,
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
    rng = quote(f"'{tab}'", safe="")  # имя листа в кавычках — в нём пробелы и скобки
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
