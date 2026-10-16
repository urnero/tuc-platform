"""Точка входа API. Пока только проверка здоровья и ping."""

from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="ТУЦ API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """Для Caddy, CI и мониторинга: отвечает, если процесс жив."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/api/v1/ping")
def ping() -> dict:
    return {"pong": True}
