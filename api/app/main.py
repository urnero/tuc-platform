"""Точка входа API: здоровье, ping, загрузка моделей, расчёт печати, цена, заказы, оплата."""

from fastapi import FastAPI

from app.config import settings
from app.orders import router as orders_router
from app.payments import router as payments_router
from app.quotes import router as quotes_router
from app.slices import router as slices_router
from app.uploads import router as uploads_router

app = FastAPI(title="ТУЦ API", version="0.1.0")
app.include_router(uploads_router)
app.include_router(slices_router)
app.include_router(quotes_router)
app.include_router(orders_router)
app.include_router(payments_router)


@app.get("/health")
def health() -> dict:
    """Для Caddy, CI и мониторинга: отвечает, если процесс жив."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/api/v1/ping")
def ping() -> dict:
    return {"pong": True}
