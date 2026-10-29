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
    # Цвета пластика для раскраски по частям (B31): key, name, hex. После правки перезапустить api.
    colors_path: Path = Path("config/colors.yaml")
    # Справочник материалов (B44): свойства, цвета, max размер; смолы — «по запросу».
    materials_path: Path = Path("config/materials.yaml")
    # Каталог готовых моделей (B20): catalog.yaml + models/. В docker монтируется как /srv/catalog.
    catalog_dir: Path = Path("catalog")

    # Загрузка моделей (B02)
    # Префикс номера заказа: «BP-12». Старые заказы в таблице учёта остались с «ТУЦ-» (B40b).
    order_number_prefix: str = "BP"
    max_upload_mb: int = 100
    # Рабочая область самого большого FDM-принтера (Bambu P1S, docs/PRINTERS.md), мм: X×Y×Z.
    # Модель больше этого — предупреждение «печатаем частями или по запросу».
    print_bed_mm: str = "256x256x256"
    # Защита от цикла запросов (app/limits.py): сколько раз в минуту с одного IP можно
    # создавать загрузки (файл, каталог, редактор, тиснение) и заказы. 0 = без ограничений.
    rate_limit_uploads_per_min: int = 10
    rate_limit_orders_per_min: int = 5
    # Если на диске с DATA_DIR свободно меньше, новые загрузки получают 503. 0 = не проверять.
    min_free_disk_gb: float = 2
    # Сколько часов действует расчёт цены (quote). Старше — заказ по нему не оформить (410):
    # цены в pricing.yaml могли измениться. 0 = без срока.
    quote_ttl_hours: int = 24

    # Слайсинг (B04)
    profiles_dir: Path = Path("profiles")  # ini-профили PrusaSlicer: printer, print, filament/*
    # Команда слайсера; в worker — путь к распакованному AppImage.
    prusa_slicer_bin: str = "prusa-slicer"
    slice_timeout_s: int = 600  # сколько ждём слайсер на одну модель
    # Пустой REDIS_URL = очереди нет, слайсим прямо в API (разработка и тесты).
    redis_url: str = "redis://localhost:6379/0"

    # Параметрические редакторы (B21): editors/<slug>/editor.yaml + model.scad.
    # В docker монтируется как /srv/editors. OpenSCAD стоит только в контейнере worker.
    editors_dir: Path = Path("editors")
    openscad_bin: str = "openscad"
    openscad_timeout_s: int = 120  # сколько ждём OpenSCAD на одну модель

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
    # B47: строка заказа в таблице сразу при создании и смене статуса.
    # false — только ночная выгрузка.
    google_sheet_live: bool = True

    # Автоудаление файлов моделей (B15) — сроки из политики ПДн (/policy, раздел 6).
    # Загрузки без заказа — через 30 дней, файлы закрытых заказов — через год. 0 = не удалять.
    cleanup_uploads_days: int = 30
    cleanup_order_files_days: int = 365
    # Обезличивание заказов (B35): через 5 лет после закрытия заказа стираем данные клиента
    # (имя, телефон, e-mail, адрес…), суммы и материалы остаются. 0 = не обезличивать.
    anonymize_orders_days: int = 5 * 365 + 1

    # Админка (B09): /admin за basic auth. Пустой логин или пароль = админка выключена (503).
    admin_user: str = "admin"
    admin_password: str = ""

    # Письма (app/mailer.py): код для входа в кабинет (B32). Пустой SMTP_HOST = письма не
    # отправляются, вход в кабинет отвечает 503. SMTP_HOST=log — письмо пишется в лог api
    # (для разработки без почты). SMTP_SSL: true — порт 465 (TLS сразу), false — 587 (STARTTLS).
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # адрес отправителя; пусто = SMTP_USER
    smtp_ssl: bool = True
    # Почта владельца для заявок «цена по запросу» (смолы): копия карточки из Telegram.
    # Пусто или SMTP_HOST пуст = писем нет, заявка видна в Telegram и /admin/leads.
    owner_email: str = ""

    # Кабинет клиента (B32): вход по коду из письма.
    login_code_ttl_min: int = 15  # сколько минут действует код
    session_days: int = 30  # сколько дней держим вход (cookie tuc_session)
    rate_limit_login_per_min: int = 5  # запросов кода и попыток входа в минуту с одного IP

    @field_validator("google_sa_json_path", mode="before")
    @classmethod
    def _empty_path_is_none(cls, v):
        """Пустое GOOGLE_SA_JSON_PATH= в .env — это «не задано», а не путь «.»."""
        return None if v in ("", None) else v

    @property
    def print_bed(self) -> tuple[float, float, float]:
        """«256x256x256» → (256.0, 256.0, 256.0)."""
        x, y, z = (float(v) for v in self.print_bed_mm.lower().split("x"))
        return (x, y, z)


settings = Settings()
