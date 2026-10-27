"""Точка входа API: здоровье, загрузка и каталог моделей, редакторы, тиснение, расчёт печати,
цена, заказы, оплата, кабинет клиента."""

from fastapi import FastAPI

from app.account import router as account_router
from app.admin import router as admin_router
from app.catalog import router as catalog_router
from app.config import settings
from app.editors import router as editors_router
from app.emboss import router as emboss_router
from app.orders import router as orders_router
from app.paint import router as paint_router
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
app.include_router(admin_router)
app.include_router(catalog_router)
app.include_router(editors_router)
app.include_router(emboss_router)
app.include_router(paint_router)
app.include_router(account_router)


@app.get("/health")
def health() -> dict:
    """Для Caddy, CI и мониторинга: отвечает, если процесс жив."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/api/v1/ping")
def ping() -> dict:
    return {"pong": True}
