"""Точка входа API: здоровье, ping, загрузка моделей."""

from fastapi import FastAPI

from app.config import settings
from app.uploads import router as uploads_router

app = FastAPI(title="ТУЦ API", version="0.1.0")
app.include_router(uploads_router)


@app.get("/health")
def health() -> dict:
    """Для Caddy, CI и мониторинга: отвечает, если процесс жив."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/api/v1/ping")
def ping() -> dict:
    return {"pong": True}
