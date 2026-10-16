"""Настройки приложения. Берутся из переменных окружения или файла .env."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    site_url: str = "http://localhost:8080"
    data_dir: Path = Path("./data")
    pricing_path: Path = Path("config/pricing.yaml")

    database_url: str = "postgresql+psycopg://tuc:change_me@localhost:5432/tuc"
    redis_url: str = "redis://localhost:6379/0"

    telegram_bot_token: str = ""
    telegram_owner_chat_id: str = ""
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""


settings = Settings()
