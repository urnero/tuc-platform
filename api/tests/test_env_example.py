"""Проверка .env.example в корне репозитория: с него bootstrap.sh делает .env на сервере."""

import re
from pathlib import Path

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def test_no_comment_after_empty_value():
    # `KEY=   # пояснение` docker compose читает как значение «# пояснение» —
    # бот получил бы такой «токен», а ЮKassa считалась бы настроенной.
    bad = [
        line
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if re.match(r"^[A-Z0-9_]+=\s*#", line)
    ]
    assert bad == [], f"комментарий после пустого значения перенесите строкой выше: {bad}"


def test_all_settings_listed():
    # Каждая настройка приложения должна быть в .env.example, иначе владелец о ней не узнает.
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    listed = set(re.findall(r"^([A-Z0-9_]+)=", text, flags=re.M))
    internal = {"yookassa_api_url"}  # адрес API ЮKassa меняют только тесты
    missing = [
        name.upper()
        for name in Settings.model_fields
        if name not in internal and name.upper() not in listed
    ]
    assert missing == [], f"добавьте в .env.example: {missing}"
