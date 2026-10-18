# Платформа ТУЦ

Сайт студии 3D-печати ТУЦ: загрузка модели → расчёт цены → заказ → оплата → учёт и Telegram.

Разработку ведут запланированные сессии Claude. Правила — в `CLAUDE.md`. Что строим — в `docs/SPEC.md`. Что сделано — в `docs/STATUS.md`.

## Запуск локально

Нужен Docker.

```bash
cp .env.example .env
docker compose up --build
```

- Сайт: http://localhost:8080
- Загрузка модели: http://localhost:8080/upload
- API: http://localhost:8080/api/v1/ping
- Здоровье: http://localhost:8080/health

## Разработка без Docker

```bash
cd api && pip install -e ".[dev]" && uvicorn app.main:app --reload --port 8000
cd web && npm ci && npm run dev
```

## Структура

```
api/      FastAPI, БД, расчёт цены, заказы, вебхуки
          app/uploads.py — приём STL/3MF, app/meshcheck.py — проверка сетки (trimesh)
web/      Next.js: сайт, 3D-просмотр, редакторы, оформление заказа
config/   pricing.yaml — цены материалов и ставки
docs/     SPEC, BACKLOG, STATUS, DECISIONS
Caddyfile обратный прокси: / → web, /api и /health → api
```
