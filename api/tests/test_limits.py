"""Защита от цикла запросов и переполнения диска (app/limits.py).

В conftest лимиты для всех тестов выключены (autouse-фикстура no_limits), здесь включаем их
точечно через settings.
"""

import shutil

from conftest import box_stl
from fastapi import Request

from app import limits
from app.config import settings
from app.limits import RateLimiter, client_ip


def _post(client, headers=None):
    return client.post(
        "/api/v1/uploads",
        files={"file": ("box.stl", box_stl(), "model/stl")},
        headers=headers or {},
    )


# --- счётчик ---------------------------------------------------------------------------


def test_limiter_sliding_window():
    lim = RateLimiter()
    assert lim.hit("a", 2, now=100.0) is None
    assert lim.hit("a", 2, now=110.0) is None
    wait = lim.hit("a", 2, now=120.0)  # третий за минуту — нельзя
    assert wait == 40.0  # первый запрос (100.0) выйдет из окна через 40 с
    assert lim.hit("b", 2, now=120.0) is None  # другой ключ не связан
    assert lim.hit("a", 2, now=160.0) is None  # окно сдвинулось — можно


def test_limiter_zero_is_unlimited():
    lim = RateLimiter()
    assert all(lim.hit("a", 0, now=1.0) is None for _ in range(100))


def test_limiter_prunes_stale_keys():
    lim = RateLimiter()
    for i in range(10_001):
        lim.hit(f"ip{i}", 5, now=0.0)
    lim.hit("fresh", 5, now=1000.0)  # запись > 10 000 ключей → чистка старых
    assert set(lim._hits) == {"fresh"}


# --- IP клиента ------------------------------------------------------------------------


def _request(headers: dict, client=("10.0.0.5", 1234)) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": client})


def test_client_ip_prefers_forwarded_for():
    assert client_ip(_request({})) == "10.0.0.5"
    assert client_ip(_request({"X-Forwarded-For": "203.0.113.7"})) == "203.0.113.7"
    # несколько прокси — берём ближайший к нам (последний), его подделать нельзя
    assert client_ip(_request({"X-Forwarded-For": "1.1.1.1, 203.0.113.7"})) == "203.0.113.7"
    assert client_ip(_request({}, client=None)) == "unknown"


# --- API: загрузки ---------------------------------------------------------------------


def test_uploads_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_uploads_per_min", 2)
    a = {"X-Forwarded-For": "203.0.113.1"}
    b = {"X-Forwarded-For": "203.0.113.2"}
    assert _post(client, a).status_code == 201
    assert _post(client, a).status_code == 201
    r = _post(client, a)
    assert r.status_code == 429, r.text
    assert "Подождите минуту" in r.json()["detail"]
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert _post(client, b).status_code == 201  # другой клиент не страдает


def test_rate_limit_covers_catalog_and_orders_separately(client, monkeypatch):
    """Каталог и редактор создают загрузки — у них общий счётчик с POST /uploads;
    у заказов свой."""
    monkeypatch.setattr(settings, "rate_limit_uploads_per_min", 1)
    monkeypatch.setattr(settings, "rate_limit_orders_per_min", 1)
    assert _post(client).status_code == 201
    assert _post(client).status_code == 429
    # кнопка «Заказать» в каталоге упирается в тот же лимит загрузок
    assert client.post("/api/v1/catalog/nope/upload").status_code == 429
    # заказ: первый проходит до проверки расчёта (404 — расчёта нет), второй — 429
    body = {"name": "Иван", "phone": "8 999 123-45-67", "consent": True, "quote_id": "x" * 32}
    assert client.post("/api/v1/orders", json=body).status_code == 404
    assert client.post("/api/v1/orders", json=body).status_code == 429


def test_uploads_503_when_disk_is_full(client, monkeypatch, data_dir):
    monkeypatch.setattr(settings, "min_free_disk_gb", 2)
    usage = shutil.disk_usage(data_dir)._replace(free=1 * 1024**3)
    monkeypatch.setattr(limits.shutil, "disk_usage", lambda p: usage)
    r = _post(client)
    assert r.status_code == 503, r.text
    assert "место" in r.json()["detail"]
    assert not (data_dir / "uploads").exists()  # ничего не записали

    usage = usage._replace(free=3 * 1024**3)
    assert _post(client).status_code == 201


def test_free_disk_gb_works_before_data_dir_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "нет" / "такой" / "папки")
    assert limits.free_disk_gb() > 0
