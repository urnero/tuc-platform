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
- Загрузка модели: http://localhost:8080/upload (после загрузки — страница модели с 3D-просмотром и расчётом печати)
- Админка владельца: http://localhost:8080/admin (логин и пароль — `ADMIN_USER` / `ADMIN_PASSWORD` из `.env`)
- API: http://localhost:8080/api/v1/ping
- Здоровье: http://localhost:8080/health

## Сервер

Один VPS, стенды `prod` (ветка `main`) и `staging` (ветка `dev`), общий Caddy с HTTPS. Первичная
настройка — `deploy/bootstrap.sh`, дальше деплой делают GitHub Actions после зелёного CI.
Пошагово — `docs/DEPLOY.md`.

## Разработка без Docker

```bash
cd api && pip install -e ".[dev]" && uvicorn app.main:app --reload --port 8000
cd web && npm ci && npm run dev
```

Расчёт печати без Docker: поставь PrusaSlicer (`PRUSA_SLICER_BIN=/путь/к/prusa-slicer`), укажи
`PROFILES_DIR=../profiles` и оставь `REDIS_URL=` пустым — тогда API слайсит сам, без worker.
Для проверки без слайсера подойдёт подделка: `PRUSA_SLICER_BIN="python3 tests/fake_slicer.py"`.

## Структура

```
api/      FastAPI, БД, расчёт цены, заказы, вебхуки
          app/uploads.py — приём STL/3MF, app/meshcheck.py — проверка сетки (trimesh)
          app/slicer.py — PrusaSlicer CLI и разбор G-code, app/slices.py — API расчёта печати,
          app/worker.py — фоновые задачи (arq), app/admin.py + app/templates/admin/ — админка
          app/catalog.py — каталог готовых моделей, app/render.py — превью PNG без OpenGL
          app/editors.py — параметрические редакторы (схема → сборка STL), app/openscad.py — OpenSCAD CLI
worker/   Dockerfile: код api + PrusaSlicer (AppImage) + OpenSCAD. Считает печать и строит модели из очереди Redis
profiles/ ini-профили PrusaSlicer: printer.ini, print.ini, filament/PLA|PETG|ABS.ini
web/      Next.js: сайт, 3D-просмотр, редакторы, оформление заказа
          components/ModelViewer.tsx — Three.js просмотр STL/3MF, app/upload/[id] — страница модели
config/   pricing.yaml — цены материалов и ставки
catalog/  catalog.yaml (категории, модели) + models/*.stl — каталог готовых моделей (B20)
editors/  <slug>/editor.yaml + model.scad — параметрические редакторы (B21); образец — editors/spacer/
deploy/   сервер: bootstrap.sh (настройка VPS), deploy.sh, backup.sh, compose.server.yml, edge/ (общий Caddy, HTTPS)
docs/     SPEC, BACKLOG, STATUS, DECISIONS, DEPLOY
Caddyfile обратный прокси для локального запуска: / → web, /api, /admin и /health → api
```
