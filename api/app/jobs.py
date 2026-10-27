"""Общее для фоновых задач с записью-статусом: расчёт печати (B04), сборка редактора (B21),
тиснение (B30). У каждой — json-запись в DATA_DIR со статусом queued → running → done | error.

Две беды, которые здесь лечим (QA 2026-10-22, баг «НЕДОСТУПНОСТЬ»):

1. Redis недоступен в момент постановки в очередь. Раньше запись сохранялась ДО постановки,
   `enqueue` падал с 500, а запись оставалась `queued` навсегда: повторный POST отвечал
   «уже считаем», клиент ждал вечно. Теперь API зовёт `enqueue(...)`, при ошибке очереди
   удаляет свою запись и отвечает 503 — клиент видит понятный текст и может нажать ещё раз.

2. Worker упал / перезапущен / arq снял задачу по таймауту — запись застыла в `queued`
   или `running`. Такая запись старше `stuck_after_s()` считается брошенной: `settle()`
   переводит её в `error` с понятным текстом (GET покажет ошибку, опрос на сайте
   остановится), а следующий POST ставит задачу заново под новым id (`retry_job_id`):
   arq не берёт повторно id, результат которого ещё хранит (keep_result = 1 час).

Запас времени один на все задачи — слайсер самый долгий, и очередь общая (max_jobs = 1):
задача в `queued` может честно ждать, пока досчитается чужая модель.
"""

from datetime import UTC, datetime

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from app.config import settings

# Сколько arq даёт задаче сверх таймаута самого слайсера (на запуск процесса, запись файлов).
JOB_TIMEOUT_EXTRA_S = 60

STUCK_ERROR = (
    "Задача не завершилась в срок — очередь или сервер расчёта были недоступны. Попробуйте ещё раз."
)
QUEUE_UNAVAILABLE = "Очередь расчётов недоступна. Попробуйте через минуту."


class QueueUnavailable(Exception):
    """Не удалось положить задачу в arq (Redis не отвечает)."""


def job_timeout_s() -> int:
    """Таймаут одной задачи в worker (WorkerSettings.job_timeout)."""
    return settings.slice_timeout_s + JOB_TIMEOUT_EXTRA_S


def stuck_after_s() -> int:
    """Через сколько секунд запись `queued`/`running` считаем брошенной.

    Равно таймауту задачи в worker: если за это время задача не закончилась ни успехом,
    ни ошибкой, worker её уже убил (или так и не получил).
    """
    return job_timeout_s()


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def is_stuck(record: dict, now: datetime | None = None) -> bool:
    """`queued`/`running` старше stuck_after_s() — брошена.

    Для `running` отсчёт от `started_at` (когда worker взял задачу), для `queued` —
    от `created_at`. Запись без дат (старый формат) — не трогаем."""
    if record.get("status") not in ("queued", "running"):
        return False
    since = _parse(record.get("started_at")) if record["status"] == "running" else None
    since = since or _parse(record.get("created_at"))
    if since is None:
        return False
    age = ((now or _now()) - since).total_seconds()
    return age > stuck_after_s()


def settle(record: dict | None, save) -> dict | None:
    """Брошенную запись переводит в `error` и сохраняет через `save(record)`.

    Зовётся из GET и POST перед тем, как отдать запись клиенту: вместо вечного «в очереди»
    клиент получает ошибку с текстом STUCK_ERROR и кнопку «ещё раз»."""
    if record is None or not is_stuck(record):
        return record
    record.update(status="error", error=STUCK_ERROR)
    record["finished_at"] = _now().isoformat(timespec="seconds")
    save(record)
    return record


def next_attempt(previous: dict | None) -> int:
    """Номер попытки для новой записи: 0, если прежней записи нет, иначе её attempt + 1."""
    if previous is None:
        return 0
    return int(previous.get("attempt", 0)) + 1


def retry_job_id(base: str, attempt: int) -> str:
    """Id задачи arq. Первая попытка — как раньше; повторные — с суффиксом `:r<n>`,
    иначе arq промолчит: id с сохранённым результатом (в т. ч. ошибкой таймаута) он не берёт."""
    return base if attempt <= 0 else f"{base}:r{attempt}"


def redis_settings() -> RedisSettings:
    # Пустой REDIS_URL бывает только в разработке без очереди — воркер тогда не запускают,
    # а API считает сам. Чтобы импорт модуля не падал, подставляем localhost.
    return RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")


async def enqueue(request: Request, function: str, *args, job_id: str) -> None:
    """Кладёт задачу в arq. Пул соединений с Redis — один на процесс (в app.state).

    Redis не отвечает → QueueUnavailable (вызывающий удаляет свою запись и отвечает 503).
    Сломанный пул выбрасываем, чтобы следующий запрос подключился заново."""
    pool = getattr(request.app.state, "arq_pool", None)
    try:
        if pool is None:
            # В API не ждём Redis по 5 секунд (как worker при старте): одна попытка, и 503.
            rs = redis_settings()
            rs.conn_retries = 1
            pool = await create_pool(rs)
            request.app.state.arq_pool = pool
        await pool.enqueue_job(function, *args, _job_id=job_id)
    except (RedisError, OSError, TimeoutError) as e:
        request.app.state.arq_pool = None
        raise QueueUnavailable(str(e)) from e


def queue_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail=QUEUE_UNAVAILABLE)
