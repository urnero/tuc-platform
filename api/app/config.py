"""Настройки приложения. Берутся из переменных окружения или файла .env."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    site_url: str = "http://localhost:8080"
    data_dir: Path = Path("./data")
    pricing_path: Path = Path("config/pricing.yaml")
    # Каталог готовых моделей (B20): catalog.yaml + models/. В docker монтируется как /srv/catalog.
    catalog_dir: Path = Path("catalog")

    # Загрузка моделей (B02)
    max_upload_mb: int = 100
    # Рабочая область принтера, мм: X×Y×Z. Модель больше этого — предупреждение.
    print_bed_mm: str = "250x210x220"

    # Слайсинг (B04)
    profiles_dir: Path = Path("profiles")  # ini-профили PrusaSlicer: printer, print, filament/*
    # Команда слайсера; в worker — путь к распакованному AppImage.
    prusa_slicer_bin: str = "prusa-slicer"
    slice_timeout_s: int = 600  # сколько ждём слайсер на одну модель
    # Пустой REDIS_URL = очереди нет, слайсим прямо в API (разработка и тесты).
    redis_url: str = "redis://localhost:6379/0"

    database_url: str = "postgresql+psycopg://tuc:change_me@localhost:5432/tuc"

    telegram_bot_token: str = ""
    telegram_owner_chat_id: str = ""
    # ЮKassa (B08). Пустой shop_id или ключ = онлайн-оплата выключена, кнопки на сайте нет.
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_api_url: str = "https://api.yookassa.ru/v3"
    # Ставка НДС для чека 54-ФЗ (1 — без НДС, 2 — 0 %, 3 — 10 %, 4 — 20 %, …).
    # Пусто = чек в платёж не вкладываем (самозанятый / чеки ЮKassa не подключены).
    yookassa_vat_code: str = ""

    # Google-таблица учёта (B11): JSON-ключ сервисного аккаунта и id таблицы из её адреса.
    # Пусто = ночной экспорт выключен. Лист переписывается целиком каждую ночь.
    google_sa_json_path: Path | None = None
    google_sheet_id: str = ""
    google_sheet_tab: str = "Заказы (сайт)"

    # Автоудаление файлов моделей (B15) — сроки из политики ПДн (/policy, раздел 6).
    # Загрузки без заказа — через 30 дней, файлы закрытых заказов — через год. 0 = не удалять.
    cleanup_uploads_days: int = 30
    cleanup_order_files_days: int = 365

    # Админка (B09): /admin за basic auth. Пустой логин или пароль = админка выключена (503).
    admin_user: str = "admin"
    admin_password: str = ""

    @field_validator("google_sa_json_path", mode="before")
    @classmethod
    def _empty_path_is_none(cls, v):
        """Пустое GOOGLE_SA_JSON_PATH= в .env — это «не задано», а не путь «.»."""
        return None if v in ("", None) else v

    @property
    def print_bed(self) -> tuple[float, float, float]:
        """«250x210x220» → (250.0, 210.0, 220.0)."""
        x, y, z = (float(v) for v in self.print_bed_mm.lower().split("x"))
        return (x, y, z)


settings = Settings()
