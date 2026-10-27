FROM python:3.12-slim-bookworm

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir .

# config/pricing.yaml монтируется из корня репо (см. docker-compose: ./config:/srv/config)

EXPOSE 8000
# Перед стартом применяем миграции БД (alembic/versions), потом поднимаем API.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
