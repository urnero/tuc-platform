"""B2B (B33): проверка реквизитов юрлица или ИП в заказе.

Организация или ИП заказывает так же, как частное лицо, но в форме заказа ставит галочку
«от организации» и вписывает наименование, ИНН, КПП (только у организаций) и юридический
адрес. Такой заказ платится не картой через ЮKassa, а по счёту безналом
(`orders.payment_method = "invoice"`): счёт рисует сайт на странице заказа
(`/order/<token>/invoice`) из реквизитов студии (`web/lib/company.ts`) и реквизитов
покупателя, которые лежат в заказе. Когда деньги пришли на счёт, владелец ставит
заказу «оплачен» кнопкой в Telegram или в админке.

Здесь — проверка ИНН и КПП и подсказка по ИНН (`GET /api/v1/company/lookup?inn=…`):
по ИНН сайт подставляет наименование, КПП и юридический адрес из ЕГРЮЛ/ЕГРИП через DaData
(бесплатный тариф — 10 000 запросов в сутки). Нет ключа `DADATA_API_KEY` — ручка отвечает
`{"enabled": false}`, и клиент просто вписывает реквизиты руками, как раньше.
Сумма прописью и сам бланк счёта — на сайте (`web/lib/invoice.ts`), чтобы реквизиты студии
не дублировать в API.
"""

import logging
import re
import threading

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.limits import lookup_guard

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["b2b"])

# Веса контрольных сумм ИНН (ФНС): для 10 цифр — одна сумма по 9 первым,
# для 12 цифр — две (11-я цифра по первым 10, 12-я по первым 11).
_W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11 % 10


def inn_kind(inn: str) -> str | None:
    """«7707083893» → «org» (организация, 10 цифр), «500100732259» → «ip» (ИП или физлицо,
    12 цифр), иначе None — не ИНН: не те длина или контрольные цифры."""
    inn = re.sub(r"\s", "", inn or "")
    if not inn.isdigit():
        return None
    if len(inn) == 10:
        return "org" if _check_digit(inn[:9], _W10) == int(inn[9]) else None
    if len(inn) == 12:
        ok = _check_digit(inn[:10], _W11) == int(inn[10]) and _check_digit(inn[:11], _W12) == int(
            inn[11]
        )
        return "ip" if ok else None
    return None


def is_valid_kpp(kpp: str) -> bool:
    """КПП — 9 знаков: 4 цифры, 2 цифры или заглавные латинские буквы, 3 цифры."""
    return re.fullmatch(r"\d{4}[\dA-Z]{2}\d{3}", kpp or "") is not None


class Company(BaseModel):
    """Блок `company` в POST /api/v1/orders. Есть блок — заказ от организации, оплата по счёту."""

    name: str = Field(min_length=1, max_length=300)  # «ООО „Ромашка“» или «ИП Иванов И. И.»
    inn: str = Field(min_length=10, max_length=14)
    kpp: str | None = Field(default=None, max_length=12)
    address: str | None = Field(default=None, max_length=1000)  # юридический адрес

    @field_validator("kpp", "address", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v:
            raise ValueError("Укажите наименование организации или ИП.")
        return v

    @field_validator("inn", mode="before")
    @classmethod
    def _inn(cls, v):
        v = re.sub(r"\s", "", str(v or ""))
        if inn_kind(v) is None:
            raise ValueError("Проверьте ИНН: 10 цифр у организации, 12 — у ИП.")
        return v

    @field_validator("kpp")
    @classmethod
    def _kpp(cls, v):
        if v is not None and not is_valid_kpp(v):
            raise ValueError("Проверьте КПП: 9 знаков, например 770101001.")
        return v

    def to_columns(self) -> dict:
        """Поля для строки `orders`."""
        return {
            "company_name": self.name,
            "company_inn": self.inn,
            # У ИП КПП нет — даже если прислали, не сохраняем.
            "company_kpp": self.kpp if inn_kind(self.inn) == "org" else None,
            "company_address": self.address,
        }


# --- Подсказка по ИНН (DaData) ---------------------------------------------------------------

DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
TRANSPORT: httpx.BaseTransport | None = None  # тесты подставляют поддельную DaData
TIMEOUT_S = 5  # клиент ждёт подсказку у поля ИНН — дольше не держим

# Ответы DaData по ИНН меняются редко — помним в памяти процесса api, чтобы повторный ввод
# того же ИНН (вернулся на форму, обновил страницу) не тратил суточный лимит.
_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
CACHE_MAX = 5000

# Статусы из ЕГРЮЛ, при которых счёт выставлять не стоит — сайт покажет предупреждение.
INACTIVE = {"LIQUIDATING", "LIQUIDATED", "BANKRUPT", "REORGANIZING"}


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def parse_party(answer: dict) -> dict:
    """Ответ DaData findById/party → то, что нужно форме заказа.

    Берём первую подсказку (головная организация): короткое наименование с формой
    («ООО «Ромашка»», «ИП Иванов Иван Иванович»), КПП (у ИП его нет), адрес как в ЕГРЮЛ
    и статус. Ничего не нашлось — `{"found": False}`."""
    items = answer.get("suggestions") or []
    if not items:
        return {"found": False}
    first = items[0]
    data = first.get("data") or {}
    name = ((data.get("name") or {}).get("short_with_opf") or first.get("value") or "").strip()
    addr = data.get("address") or {}
    address = addr.get("unrestricted_value") or addr.get("value") or ""
    status = (data.get("state") or {}).get("status") or None
    kpp = data.get("kpp") if data.get("type") != "INDIVIDUAL" else None
    return {
        "found": bool(name),
        "name": name or None,
        "kpp": kpp if kpp and is_valid_kpp(kpp) else None,
        "address": address.strip() or None,
        "status": status,
        "active": status not in INACTIVE,
    }


def lookup_party(inn: str) -> dict:
    """Ищет организацию или ИП по ИНН. Без ключа — `{"enabled": False, "found": False}`.
    Ошибка сети или DaData — `{"found": False}`: подсказка не главное, заказ не ломаем."""
    if not settings.dadata_api_key:
        return {"enabled": False, "found": False}
    with _cache_lock:
        if inn in _cache:
            return _cache[inn]
    try:
        with httpx.Client(timeout=TIMEOUT_S, transport=TRANSPORT) as client:
            r = client.post(
                DADATA_URL,
                json={"query": inn, "branch_type": "MAIN"},
                headers={
                    "Authorization": f"Token {settings.dadata_api_key}",
                    "Accept": "application/json",
                },
            )
        r.raise_for_status()
        result = {"enabled": True, **parse_party(r.json())}
    except (httpx.HTTPError, ValueError) as e:
        log.warning("DaData: не получили реквизиты по ИНН: %s", e)
        return {"enabled": True, "found": False}
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[inn] = result
    return result


@router.get("/company/lookup", dependencies=[Depends(lookup_guard)])
def company_lookup(inn: str) -> dict:
    """Подсказка для формы заказа: по ИНН — наименование, КПП, юридический адрес, статус."""
    inn = re.sub(r"\s", "", inn)
    if inn_kind(inn) is None:
        raise HTTPException(422, detail="Проверьте ИНН: 10 цифр у организации, 12 — у ИП.")
    return lookup_party(inn)
