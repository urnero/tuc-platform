# Бэклог

Порядок = приоритет. Статусы: `todo` / `doing` / `done` / `blocked (причина)`.
Баги добавляются в начало строкой `BUG todo fix: <что> — <где> — <как воспроизвести>`.

## Баги (QA 2026-10-22; критичные первыми)

- BUG done fix: [НЕДОСТУПНОСТЬ] расчёт печати, сборка редактора и тиснение могли навсегда зависнуть в `queued`/`running` (Redis недоступен при постановке → 500, запись оставалась; worker упал / arq снял по таймауту) — исправлено, общий код `api/app/jobs.py`: при ошибке очереди запись удаляется и ответ 503 «Очередь расчётов недоступна»; запись `queued`/`running` старше таймаута worker (`slice_timeout_s + 60`) при GET/POST становится `error` «Задача не завершилась в срок… Попробуйте ещё раз», повторный POST ставит задачу заново под новым id arq (`attempt`, суффикс `:r<n>`); в записях появились `attempt` и `started_at`. Тесты `tests/test_jobs.py` (12), запись в DECISIONS.md.
- BUG doing (2026-10-26 00:38 МСК) fix: [БЕЗОПАСНОСТЬ] 3MF — это zip, распакованный размер не проверяется: zip-бомба в 100 МБ (лимит) разворачивается в гигабайты XML в памяти api → OOM, контейнер падает — `api/app/meshcheck.py::inspect_mesh` (`trimesh.load(…, file_type="3mf")`) — воспроизвести: файл `3D/3dmodel.model` из 1 ГБ пробелов внутри zip → переименовать в `.3mf` → `POST /uploads`. Чинить: перед trimesh открыть `zipfile`, сумма `file_size` записей ≤ например 500 МБ и отношение ≤ 50×, иначе 422; тест.
- BUG todo fix: [БЕЗОПАСНОСТЬ/ДИСК] нет ограничений частоты и квот: `POST /api/v1/uploads` (до 100 МБ каждый), `POST /catalog/{slug}/upload`, `POST /editors/{slug}/builds/{id}/upload`, `POST /uploads/{id}/embosses` и `POST /api/v1/orders` можно дёргать в цикле — диск забивается копиями, БД и Telegram владельца — мусорными заказами (каждый заказ = сообщение боту) — воспроизвести: `for i in $(seq 1000); do curl -F file=@box.stl …/api/v1/uploads; done`. Чинить: `rate_limit` в Caddy (`deploy/edge/site.caddy.tmpl`) на `/api/v1/uploads*` и `/api/v1/orders` по IP (например 10/мин), проверка свободного места в `DATA_DIR` перед записью (503 при < 2 ГБ); документировать в DEPLOY.md.
- BUG todo fix: [ДЕНЬГИ, низкий] расчёт цены (quote) не имеет срока и не одноразовый: старый `quote_id` принимает заказ по старой цене после правки `config/pricing.yaml`, один расчёт позволяет оформить сколько угодно заказов — `api/app/quotes.py::load_quote`, `api/app/orders.py::create_order` — воспроизвести: сделать `/quote`, поменять цены в yaml, перезапустить api, `POST /orders` с тем же `quote_id` → заказ по старой сумме. Чинить: 410 для расчёта старше 24 ч (`created_at` в json); тест.
- BUG todo fix: [ПРОИЗВОДИТЕЛЬНОСТЬ] вебхук ЮKassa объявлен `async def`, но внутри синхронно ходит в ЮKassa (`httpx`, таймаут 20 с) и в БД — на время ответа ЮKassa замирает весь API (один event loop) — `api/app/payments.py::yookassa_webhook` — воспроизвести: подменить `yookassa_api_url` на сервер, отвечающий через 15 с, прислать вебхук и параллельно `GET /health` — ждёт. Чинить: сделать обработчик обычным `def` (FastAPI сам уведёт в threadpool) и принимать тело параметром `body: dict`, либо `await run_in_threadpool(sync_payment, …)`.
- BUG done fix: [ДЕНЬГИ] смена единиц «мм → дюймы» после готового расчёта печати не сбрасывала расчёт: граммы и часы оставались от модели в мм (в 16 000 раз меньше), цена и заказ считались по ним — `api/app/uploads.py::patch_upload`, `api/app/slices.py` — исправлено: PATCH units удаляет папки `slices/` и `quotes/` (у заказов свой снимок расчёта в БД); запись расчёта печати хранит `units`, запись для других единиц не отдаётся и не блокирует новый расчёт (`slice_jobs.load_record(..., units=)`), id задачи arq тоже с единицами; расчёт цены хранит `units`; на странице модели калькулятор перерисовывается после смены единиц. Тесты: `test_slice_api_units_change_resets_record`, `test_slice_api_stale_record_for_other_units_is_ignored`, `test_api_quote_units_change_invalidates`, `test_create_order_after_units_change_404`.
- BUG done fix: CSV админки — имя/комментарий/адрес клиента вида `=HYPERLINK(...)`, `+…`, `-…`, `@…` открывались в Excel как формула (CSV injection) — `api/app/admin.py::orders_csv` — исправлено: такие ячейки получают `'` впереди (`csv_safe`), тест `test_orders_csv_escapes_formulas`; в Google-таблицу значения идут RAW, там проблемы нет.
- BUG done fix: итог цены округлялся встроенным `round()` — половинки к чётному (526,5 ₽ → 526, а 527,5 → 528) — `api/app/pricing.py::calc_price` — исправлено на «половина вверх» (`math.floor(x + 0.5)`), тест `test_calc_rounds_half_up`, запись в DECISIONS.md.

## Этап 1 — MVP «загрузка → цена → оплата → учёт»

- B01 done chore: каркас репо — CLAUDE.md, docs/, docker-compose, api (FastAPI /health), web (Next hello), CI tests
- B02 done feat: загрузка STL/3MF (≤100 МБ) + проверка сетки (trimesh: watertight, bbox, объём, единицы)
- B03 done feat: 3D-просмотр модели в браузере (Three.js), габариты, выбор мм/дюймы
- B04 done feat: сервис слайсинга — PrusaSlicer CLI в worker, профили PLA/PETG/ABS, парсинг времени и граммов
- B05 done feat: калькулятор цены — pricing.yaml, выбор материала/технологии/тиража, API /quote
- B06 done feat: форма заказа — контакты, доставка/самовывоз, комментарий; orders в БД; страница статуса заказа
- B07 done feat: Telegram-бот — уведомление владельцу о новом заказе, команда /orders, смена статуса кнопками
- B08 done feat: ЮKassa — оплата (тестовый режим), вебхук, статус paid, уведомление в Telegram
- B09 done feat: админка — список заказов, фильтры, скачивание файлов (простая, за basic auth)
- B10 done chore: деплой — docs/DEPLOY.md, bootstrap.sh для VPS, GitHub Actions staging/prod, Caddy HTTPS
- B11 done feat: экспорт заказов в Google Sheet (ночью) + read-only пользователь БД для Superset
- B12 done feat: события воронки (upload, quote, order, paid) в таблицу events
- B13 done chore: оферта, политика ПДн, страница «О студии», контакты
- B14 done feat: лендинг — главная с формой загрузки, преимущества, примеры работ
- B15 done chore: автоудаление загрузок без заказа старше 30 дней и файлов выполненных заказов старше 12 месяцев (cron в worker) — сроки обещаны в политике ПДн (/policy, раздел 6)

## Этап 2 — каталог и редакторы

- B20 done feat: каталог моделей — категории, карточки, превью (рендер PNG на сервере), кнопка «заказать»
- B21 done feat: движок параметрических редакторов — OpenSCAD CLI, схема параметров → форма → STL → превью
- B22 done feat: редактор 1 — кронштейн/уголок (размеры, отверстия)
- B23 done feat: редактор 2 — коробка/органайзер (размеры, ячейки, крышка)
- B24 done feat: редактор 3 — табличка/бирка с текстом
- B25 done feat: SEO-страницы редакторов (SSR, метатеги, sitemap)

## Этап 3 — кастомизация и B2B

- B30 done feat: тиснение текста/логотипа (SVG) на загруженной модели (OpenSCAD import + extrude)
- B31 todo feat: раскраска по частям модели (выбор цвета частей, экспорт 3MF multi-color)
- B32 todo feat: кабинет клиента — история заказов, повтор заказа
- B33 todo feat: B2B — счёт для юрлица, партии, скидки
- B34 todo feat: статусы печати из Telegram → клиенту (email / Telegram)
- B35 todo chore: обезличивание заказов старше 5 лет после выполнения (имя, телефон, e-mail, адрес → пусто; суммы и материалы остаются для аналитики) — обещано в политике ПДн (/policy, раздел 6); актуально не раньше 2031 года
