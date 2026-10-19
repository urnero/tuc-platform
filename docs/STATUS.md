# Статус

## Нужно от владельца

Пока пункт не сделан, задачи, которым он нужен, помечаются `blocked`. Сборка берёт следующие.

| # | Что сделать | Нужно для | Время |
|---|---|---|---|
| 1 | Прислать реальные цены: ₽/г по материалам, ставка часа принтера, минимальный заказ, список принтеров и материалов. Вписать в `config/pricing.yaml` или прислать в чат. | B05 | 15 мин |
| 2 | VPS: Ubuntu 24.04, 2 vCPU, 4 ГБ, в РФ. Домен .ru, A-запись на VPS. | B10 | 30 мин |
| 3 | После B10: запустить `bootstrap.sh` по `docs/DEPLOY.md`, добавить SSH-ключ деплоя в GitHub Secrets. | B10 | 20 мин |
| 4 | Telegram: создать бота в @BotFather. На сервере в `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_CHAT_ID`. | B07 | 5 мин |
| 5 | ЮKassa: зарегистрировать магазин (тестовый режим доступен сразу). В `.env`: `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`. Нужна юрформа: ИП или самозанятый. | B08 | 30 мин + модерация |
| 6 | Google: сервисный аккаунт с доступом к таблице «Учет 3D-печати ТУЦ». В `.env`: `GOOGLE_SA_JSON_PATH`, `GOOGLE_SHEET_ID`. Или решение: таблицу заменяет экспорт из БД. | B11 | 20 мин |
| 7 | Проверить черновики оферты и политики ПДн, когда появятся. | B13 | 20 мин |
| 8 | Один раз собрать worker на машине с Docker: `docker compose build worker`. Если скачивание AppImage упадёт — взять актуальную ссылку на Linux x64 GTK3 AppImage с github.com/prusa3d/PrusaSlicer/releases и передать `--build-arg PRUSA_SLICER_URL=<ссылка>` (или поправить ARG в `worker/Dockerfile`). Затем на любой загрузке нажать «Рассчитать печать» и убедиться, что пришли время и граммы. По желанию: заменить `profiles/printer.ini` экспортом профиля своего принтера из PrusaSlicer. | B04 (проверка), B05 | 20 мин |

Staging: не развёрнут. Prod: не развёрнут.

## Журнал (новое сверху)

- 2026-10-19 · fix CI · После B04 CI был красный: `tests/test_slicer.py` импортировал `from tests.conftest`, что работает при `python -m pytest`, но не при `pytest` в CI (ошибка сбора, код 2). Исправлено: `from conftest import`, `pythonpath = ["."]` в pyproject. Правило добавлено в CLAUDE.md. 51 pytest зелёные обоими способами. · Нужно от владельца: без изменений (п. 1 цены, п. 8 сборка worker).

- 2026-10-18 (запуск 3) · B04 · Сервис слайсинга: `api/app/slicer.py` (команда PrusaSlicer CLI с профилями, `--scale 25.4` для дюймов, `--support-material`; разбор G-code → секунды и граммы), `api/app/slice_jobs.py` (запись расчёта `DATA_DIR/uploads/<id>/slices/<материал>[_supports].json` + G-code, статусы queued/running/done/error), `api/app/worker.py` (arq-воркер, задача `slice_upload`), API `POST/GET /api/v1/uploads/{id}/slice` и `GET /api/v1/materials`. Профили `profiles/printer.ini`, `print.ini`, `filament/PLA|PETG|ABS.ini`. `worker/Dockerfile` (python + AppImage PrusaSlicer 2.8.1) и сервис `worker` в docker-compose. На странице модели — блок «Расчёт печати» (материал, поддержки, опрос статуса, время и граммы). Проверено: путь через Redis + arq с подделкой слайсера (`tests/fake_slicer.py`) и страница в headless Chromium. Настоящий PrusaSlicer в песочнице недоступен (нет Docker, github.com закрыт) — образ worker не собирался. 51 pytest + 20 vitest зелёные, ruff/lint/tsc/build ок. · Нужно от владельца: п. 8 (собрать worker и проверить слайсер), п. 1 (цены) к B05.

- 2026-10-18 (внеплановый запуск 2) · B03 · 3D-просмотр: страница `/upload/[id]` с Three.js (@react-three/fiber + drei): STL и 3MF, вращение, сетка-пол, камера под модель. Габариты показываются в мм или дюймах. Переключатель «единицы в файле» (мм/дюймы) → `PATCH /api/v1/uploads/{id}` пересчитывает bbox/объём/предупреждения с масштабом 25,4 и сохраняет `units` в meta.json. После загрузки `/upload` ведёт на страницу модели. Проверено в headless Chromium (скриншоты STL и 3MF). 27 pytest + 12 vitest зелёные, lint/tsc/build ок. · Нужно от владельца: п. 1 (цены) к B05; для B04 — ничего (PrusaSlicer ставится в Docker сам).
- 2026-10-18 · B02 · Загрузка STL/3MF: `POST /api/v1/uploads` (лимит `MAX_UPLOAD_MB`, проверка расширения, trimesh: габариты, объём, замкнутость + автопочинка дыр, подсказка про дюймы, «не влезает в принтер» по `PRINT_BED_MM`), `GET /api/v1/uploads/{id}` и `/file`. Файлы в `DATA_DIR/uploads/<id>/`. Страница `/upload` в web (drag&drop, результат проверки, тексты предупреждений). Rewrites в next.config для dev без Caddy. 22 pytest + 11 vitest зелёные, lint/tsc/build ок. · Нужно от владельца: ничего для B03; п. 1 (цены) к B05.
- 2026-10-16 · B01 · Каркас: CLAUDE.md, docs/, docker-compose, api (FastAPI `/health`, `/api/v1/ping`), web (Next.js hello + `formatPrice`), CI (pytest, ruff, vitest, tsc). Тесты зелёные локально. · Нужно от владельца: п. 1 (цены) к B05.
- 2026-10-16 · 02:17 · Первая ночная сборка: репозиторий был недоступен приложению Claude, запуск завершился сообщением владельцу.
