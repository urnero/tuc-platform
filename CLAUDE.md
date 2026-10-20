# Платформа ТУЦ — правила для сборки

Сайт студии 3D-печати ТУЦ (Москва). Клиент загружает / выбирает / собирает модель → сервер считает печать → цена → заказ → оплата ЮKassa → заказ в БД, Google-таблице учёта и Telegram-боте владельца.

Владелец: Girg (GitHub `urnero`), продуктовый аналитик. Знает SQL, базовый Python. Пиши код и комментарии так, чтобы он мог их прочитать.

## Файлы-память проекта (читать в начале каждого запуска)

| Файл | Что там |
|---|---|
| `docs/SPEC.md` | Что хочет владелец. Стек. Формула цены. Модель данных. |
| `docs/BACKLOG.md` | Задачи по приоритету. Статусы: `todo` / `doing` / `done` / `blocked`. |
| `docs/STATUS.md` | Журнал запусков (новое сверху) и раздел «Нужно от владельца». |
| `docs/DECISIONS.md` | Решения, меняющие стек, формулу цены или архитектуру. |
| `docs/ANALYTICS.md` | Таблица `events` (воронка) и готовые SQL для владельца. Читать, когда трогаешь события. |

## Стек (менять только с записью в DECISIONS.md)

- `api/` — Python 3.12, FastAPI, SQLAlchemy 2 + Alembic (таблицы `app/models.py`, миграции `alembic/versions/`), PostgreSQL 16, Redis + arq.
- `web/` — Next.js 15 (App Router), TypeScript, Tailwind, Three.js (@react-three/fiber).
- `worker/` — Dockerfile: код `api/` + PrusaSlicer CLI; задачи arq в `api/app/worker.py`. Профили слайсера — `profiles/`. OpenSCAD CLI (редакторы) добавится в B21.
- Бот — не отдельный пакет: aiogram 3 в `api/app/bot.py` (запуск `python -m app.bot`, сервис `bot` в compose из образа api). Тексты/кнопки и отправка из API — `api/app/telegram.py`.
- Инфра: `docker-compose.yml` (caddy, web, api, worker, bot, postgres, redis) — локальный запуск. Сервер — `deploy/`: один VPS, стенды `/srv/tuc/prod` (main) и `/srv/tuc/staging` (dev), `compose.server.yml` поверх основного compose, общий Caddy с HTTPS в `deploy/edge`. Деплой — `.github/workflows/deploy.yml` после зелёного CI, по SSH запускает `deploy/deploy.sh`. Инструкция владельцу — `docs/DEPLOY.md`.
- Ветки: `dev` — рабочая, ночные сборки пушат сюда. `main` — прод, сливает владелец через PR.

## Как запускать

```bash
# api (тесты — на SQLite во временной папке, Postgres не нужен)
cd api && pip install -e ".[dev]" && pytest -q && ruff check .
# миграции БД (в docker контейнер api делает это сам при старте)
cd api && alembic upgrade head
# web
cd web && npm ci && npm test && npm run lint && npx tsc --noEmit
# всё вместе (нужен Docker)
cp .env.example .env && docker compose up --build
```

## Правила одного запуска

1. Прочитай `CLAUDE.md`, `docs/STATUS.md`, `docs/BACKLOG.md`.
2. Возьми первую задачу `todo` без блокера владельца. Строки `doing` пропускай — их делает соседняя ночная сессия (запуски идут каждый час с 22:37 до 03:37 МСК). `doing` старше 3 часов — брошена, можно брать.
   Застолби задачу: статус `doing (ГГГГ-ММ-ДД ЧЧ:ММ МСК)` в `docs/BACKLOG.md`, коммит только этого файла `chore: beru Bxx`, `git pull --rebase origin dev && git push origin dev`. Если задачу уже взяли — откати и выбери другую.
3. Сделай задачу: код + тесты + документация. Один запуск — одна задача.
4. Прогони тесты и линтеры. Красные тесты не пушить. Если не успеваешь — сократи задачу до рабочего состояния.
5. Коммит с префиксом `feat:` / `fix:` / `chore:` / `qa:`. Перед пушем `git pull --rebase origin dev`; конфликт в `docs/BACKLOG.md` или `docs/STATUS.md` решай, сохраняя строки обеих сторон. Пуш в `dev`.
6. Задачу → `done`. Запись в `docs/STATUS.md` сверху: дата · задача · результат · нужно от владельца.
7. Если следующим задачам нужен владелец (VPS, домен, токены, ключи, цены) — впиши в «Нужно от владельца» конкретную инструкцию: что создать, куда положить, в какую переменную `.env`.

## Жёсткие правила

- Тесты гоняй ровно как CI: `cd api && pytest -q` (не `python -m pytest`) и `cd web && npm test`. В тестах импортируй помощники как `from conftest import …`. Перед пушем проверь, что `gh api "repos/urnero/tuc-platform/actions/runs?branch=dev&per_page=1" --jq '.workflow_runs[0].conclusion'` на предыдущем коммите = success; если failure — сначала почини CI.
- Секретов в репо нет. Только `.env` (в `.gitignore`) и `.env.example` с пустыми значениями. В `.env.example` у пустой переменной комментарий пишется строкой выше, не после `=` (docker compose принял бы его за значение; есть тест `tests/test_env_example.py`).
- Загружаемые файлы: проверять размер (≤100 МБ), расширение (stl, 3mf), сетку. Файлы хранить вне репо, в `DATA_DIR`.
- Деньги: все расчёты цены — в одной функции `api/app/pricing.py` с тестами. Вебхук ЮKassa — идемпотентный.
- Не задавай вопросов владельцу внутри запуска. Прими разумное решение, запиши его в `DECISIONS.md`, продолжай.
- Не переписывай стек «потому что так лучше». Сначала запись в `DECISIONS.md`, потом код.
