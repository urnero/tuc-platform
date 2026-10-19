"""База данных (B06): подключение SQLAlchemy и сессия на запрос.

Адрес берётся из DATABASE_URL. В проде — PostgreSQL (`postgresql+psycopg://…`),
в тестах — файл SQLite во временной папке (`sqlite:///…`): тот же код, без сервера.

Схема живёт в двух местах, и они должны совпадать:
- `app/models.py` — таблицы как классы (их читает код);
- `alembic/versions/` — миграции (их применяет `alembic upgrade head` при старте api).
Тест `test_orders.py::test_alembic_matches_models` проверяет, что миграции
создают ту же схему, что и модели.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Родитель всех таблиц (см. app/models.py)."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Один движок на процесс. Кэш сбрасывает reset_engine() — нужно тестам."""
    url = settings.database_url
    # SQLite: разрешаем работу из разных потоков (TestClient ходит из своего).
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if url.startswith("sqlite"):
        # Встроенный lower() в SQLite понимает только латиницу, а в Postgres — любые буквы.
        # Подменяем его на питоновский, чтобы поиск по имени «мария» в тестах и в деве
        # работал так же, как в проде (админка B09).
        event.listen(engine, "connect", _sqlite_unicode_lower)
    return engine


def _sqlite_unicode_lower(dbapi_conn, _record) -> None:
    dbapi_conn.create_function("lower", 1, lambda s: s.lower() if isinstance(s, str) else s)


def reset_engine() -> None:
    get_engine.cache_clear()


def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: одна сессия на HTTP-запрос, закрывается после ответа."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
