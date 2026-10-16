# Бэклог

Порядок = приоритет. Статусы: `todo` / `doing` / `done` / `blocked (причина)`.
Баги добавляются в начало строкой `BUG todo fix: <что> — <где> — <как воспроизвести>`.

## Этап 1 — MVP «загрузка → цена → оплата → учёт»

- B01 done chore: каркас репо — CLAUDE.md, docs/, docker-compose, api (FastAPI /health), web (Next hello), CI tests
- B02 todo feat: загрузка STL/3MF (≤100 МБ) + проверка сетки (trimesh: watertight, bbox, объём, единицы)
- B03 todo feat: 3D-просмотр модели в браузере (Three.js), габариты, выбор мм/дюймы
- B04 todo feat: сервис слайсинга — PrusaSlicer CLI в worker, профили PLA/PETG/ABS, парсинг времени и граммов
- B05 todo feat: калькулятор цены — pricing.yaml, выбор материала/технологии/тиража, API /quote
- B06 todo feat: форма заказа — контакты, доставка/самовывоз, комментарий; orders в БД; страница статуса заказа
- B07 todo feat: Telegram-бот — уведомление владельцу о новом заказе, команда /orders, смена статуса кнопками
- B08 todo feat: ЮKassa — оплата (тестовый режим), вебхук, статус paid, уведомление в Telegram
- B09 todo feat: админка — список заказов, фильтры, скачивание файлов (простая, за basic auth)
- B10 todo chore: деплой — docs/DEPLOY.md, bootstrap.sh для VPS, GitHub Actions staging/prod, Caddy HTTPS
- B11 todo feat: экспорт заказов в Google Sheet (ночью) + read-only пользователь БД для Superset
- B12 todo feat: события воронки (upload, quote, order, paid) в таблицу events
- B13 todo chore: оферта, политика ПДн, страница «О студии», контакты
- B14 todo feat: лендинг — главная с формой загрузки, преимущества, примеры работ

## Этап 2 — каталог и редакторы

- B20 todo feat: каталог моделей — категории, карточки, превью (рендер PNG на сервере), кнопка «заказать»
- B21 todo feat: движок параметрических редакторов — OpenSCAD CLI, схема параметров → форма → STL → превью
- B22 todo feat: редактор 1 — кронштейн/уголок (размеры, отверстия)
- B23 todo feat: редактор 2 — коробка/органайзер (размеры, ячейки, крышка)
- B24 todo feat: редактор 3 — табличка/бирка с текстом
- B25 todo feat: SEO-страницы редакторов (SSR, метатеги, sitemap)

## Этап 3 — кастомизация и B2B

- B30 todo feat: тиснение текста/логотипа (SVG) на загруженной модели (OpenSCAD import + extrude)
- B31 todo feat: раскраска по частям модели (выбор цвета частей, экспорт 3MF multi-color)
- B32 todo feat: кабинет клиента — история заказов, повтор заказа
- B33 todo feat: B2B — счёт для юрлица, партии, скидки
- B34 todo feat: статусы печати из Telegram → клиенту (email / Telegram)
