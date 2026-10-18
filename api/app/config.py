"""Настройки приложения. Берутся из переменных окружения или файла .env."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    site_url: str = "http://localhost:8080"
    data_dir: Path = Path("./data")
    pricing_path: Path = Path("config/pricing.yaml")

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
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""

    @property
    def print_bed(self) -> tuple[float, float, float]:
        """«250x210x220» → (250.0, 210.0, 220.0)."""
        x, y, z = (float(v) for v in self.print_bed_mm.lower().split("x"))
        return (x, y, z)


settings = Settings()
