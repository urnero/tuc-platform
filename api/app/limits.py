"""Защита от цикла запросов и переполнения диска (BUG [БЕЗОПАСНОСТЬ/ДИСК]).

Две проверки, подключаются к ручкам как зависимости FastAPI:

- ``uploads_guard`` — на всё, что создаёт новую папку в DATA_DIR/uploads/ (загрузка файла,
  «Заказать» из каталога и редактора, тиснение): не больше RATE_LIMIT_UPLOADS_PER_MIN запросов
  в минуту с одного IP (429) и на диске есть хотя бы MIN_FREE_DISK_GB (иначе 503).
- ``orders_guard`` — на оформление заказа: RATE_LIMIT_ORDERS_PER_MIN в минуту с одного IP (429).
  Каждый заказ — строка в БД и сообщение владельцу в Telegram, мусор там хуже всего.
- ``login_guard`` — на вход в кабинет (B32): запрос кода и ввод кода, RATE_LIMIT_LOGIN_PER_MIN
  в минуту с одного IP — чтобы код нельзя было подобрать и чужую почту завалить письмами.

Счётчик живёт в памяти процесса api: один контейнер, один процесс uvicorn, Redis для этого
не нужен (и при его падении защита продолжает работать). После перезапуска api счётчики
обнуляются — для защиты от цикла это не страшно.

IP клиента берём из X-Forwarded-For: api стоит только за Caddy (порт 8000 наружу не
опубликован), а Caddy подменяет этот заголовок настоящим адресом клиента, подделать его
снаружи нельзя. Без заголовка (запуск uvicorn напрямую, тесты) — адрес соединения.

Почему не ``rate_limit`` в Caddy, как предлагалось в баге: в стандартном образе caddy:2
этой директивы нет, это сторонний плагин, под него пришлось бы собирать свой образ Caddy
на сервере. Ограничение в api проще проверить тестами и работает и на ноутбуке.
"""

import shutil
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from app.config import settings

WINDOW_S = 60  # окно «в минуту»


class RateLimiter:
    """Скользящее окно: на каждый ключ (IP) — времена последних запросов за WINDOW_S секунд."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()  # ручки заказов синхронные — работают в пуле потоков

    def hit(self, key: str, limit: int, now: float | None = None) -> float | None:
        """Учитывает запрос. Возвращает None, если можно, иначе — через сколько секунд
        освободится место в окне (для заголовка Retry-After). limit <= 0 — без ограничений."""
        if limit <= 0:
            return None
        now = time.monotonic() if now is None else now
        with self._lock:
            window = self._hits.setdefault(key, deque())
            while window and now - window[0] >= WINDOW_S:
                window.popleft()
            if len(window) >= limit:
                return WINDOW_S - (now - window[0])
            window.append(now)
            # Чтобы словарь не рос от случайных адресов, изредка выбрасываем пустые ключи.
            if len(self._hits) > 10_000:
                self._prune(now)
        return None

    def _prune(self, now: float) -> None:
        for key in [k for k, w in self._hits.items() if not w or now - w[-1] >= WINDOW_S]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        # Caddy ставит ровно один адрес; если прокси несколько — ближайший к нам последний.
        return forwarded.split(",")[-1].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _check_rate(request: Request, group: str, limit: int, what: str) -> None:
    wait = limiter.hit(f"{group}:{client_ip(request)}", limit)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много {what} подряд. Подождите минуту и попробуйте снова.",
            headers={"Retry-After": str(max(1, int(wait) + 1))},
        )


def free_disk_gb() -> float:
    """Свободное место на диске, где лежит DATA_DIR (папки может ещё не быть — берём родителя)."""
    path = settings.data_dir
    while not path.exists() and path.parent != path:
        path = path.parent
    return shutil.disk_usage(path).free / 1024**3


def check_disk_space() -> None:
    """503, если на диске меньше MIN_FREE_DISK_GB: иначе загрузка допишется наполовину, а
    следом встанут БД и слайсер. 0 = не проверять."""
    if settings.min_free_disk_gb <= 0:
        return
    if free_disk_gb() < settings.min_free_disk_gb:
        raise HTTPException(
            status_code=503,
            detail="На сервере закончилось место для файлов. Попробуйте позже.",
        )


def uploads_guard(request: Request) -> None:
    _check_rate(request, "uploads", settings.rate_limit_uploads_per_min, "загрузок")
    check_disk_space()


def orders_guard(request: Request) -> None:
    _check_rate(request, "orders", settings.rate_limit_orders_per_min, "заказов")


def login_guard(request: Request) -> None:
    _check_rate(request, "login", settings.rate_limit_login_per_min, "попыток входа")
