# Деплой на VPS

Один VPS (Ubuntu 24.04, 2 vCPU / 4 ГБ), на нём два стенда и один общий Caddy с HTTPS:

| Стенд | Папка на сервере | Ветка | Домен | Кто обновляет |
|---|---|---|---|---|
| prod | `/srv/tuc/prod` | `main` | `tuc3d.ru` (ваш) | GitHub Actions после слияния PR в `main` |
| staging | `/srv/tuc/staging` | `dev` | `staging.tuc3d.ru` | GitHub Actions после каждого пуша в `dev` (ночные сборки) |

Staging необязателен: без второго домена `bootstrap.sh` поднимает только prod. Но он полезен —
утром можно открыть тестовый сайт и посмотреть, что ночью собралось, не трогая боевой.

Каждый стенд — свой `docker compose` (web, api, worker, bot, postgres, redis), своя БД, свой `.env`,
своя папка `data/` с моделями. Общий Caddy (`deploy/edge`) слушает 80/443, сам получает сертификаты
Let's Encrypt и раздаёт запросы по домену в нужный стенд. Схема:

```
интернет → Caddy (80/443, HTTPS) ─┬─ tuc3d.ru          → tuc-prod-web-1 / tuc-prod-api-1
                                  └─ staging.tuc3d.ru  → tuc-staging-web-1 / tuc-staging-api-1
```

## Что лежит в `deploy/`

| Файл | Зачем |
|---|---|
| `bootstrap.sh` | Первичная настройка чистого VPS: Docker, файрвол, пользователь `deploy`, ключи, клоны, `.env`, запуск. Один раз. |
| `deploy.sh` | Обновить один стенд: `git reset` на нужный коммит, `docker compose up -d --build`, дождаться `/health`. Его зовут Actions. |
| `backup.sh` | `pg_dump` базы стенда в `/srv/tuc/backups/`, хранит 14 дней. Для прода стоит в cron (03:15). |
| `readonly-user.sh` + `readonly-user.sql` | Пользователь БД `tuc_ro` только для чтения — для Superset / DBeaver (B11). Запускается руками один раз на стенд. |
| `compose.server.yml` | Надстройка над `docker-compose.yml` для сервера: без локального Caddy, с `restart`, healthcheck и сетью `tuc_edge`. |
| `edge/` | Общий Caddy: `docker-compose.yml`, `Caddyfile`, шаблон домена `site.caddy.tmpl`, `render-sites.sh` (пишет `sites/*.caddy` из `.env`). |

Workflow `.github/workflows/deploy.yml` запускается после зелёного CI и по SSH выполняет на сервере
`deploy/deploy.sh <коммит>`. Красный CI на сервер не попадает.

## Шаг 1. VPS и домен (вы)

1. Купить VPS в РФ: Ubuntu 24.04, 2 vCPU, 4 ГБ, 40+ ГБ диска. При заказе добавить свой SSH-ключ —
   тогда вход `ssh root@<IP>` без пароля.
2. Купить домен `.ru`. В DNS создать A-записи на IP сервера: `@` (сам домен) и, если нужен staging,
   `staging`. Подождать, пока `ping tuc3d.ru` покажет IP сервера (обычно до часа).

Без правильного DNS Caddy не получит сертификат — проверьте DNS до запуска скрипта.

## Шаг 2. bootstrap (один раз, ~15 минут)

С ноутбука, из папки с клоном репозитория:

```bash
scp deploy/bootstrap.sh root@<IP>:
ssh root@<IP>
bash bootstrap.sh tuc3d.ru staging.tuc3d.ru you@mail.ru     # домен, тестовый домен (или -), почта для Let's Encrypt
```

Скрипт по ходу попросит добавить **ключ для чтения репозитория** (репозиторий приватный):
GitHub → репозиторий → Settings → Deploy keys → Add deploy key → вставить ключ, который он напечатал,
«Allow write access» не ставить → нажать Enter в терминале.

Дальше он сам: ставит Docker, включает файрвол (22, 80, 443), добавляет swap 2 ГБ, создаёт
пользователя `deploy`, клонирует `main` в `/srv/tuc/prod` и `dev` в `/srv/tuc/staging`, пишет `.env`
со случайными паролями БД и админки, поднимает Caddy и оба стенда (первая сборка образов — 5–10 минут:
`web` собирает Next.js, `worker` качает PrusaSlicer). В конце печатает:

- адреса сайта и админки и **пароль админки** (он же в `/srv/tuc/prod/.env`, `ADMIN_PASSWORD`);
- **приватный ключ для GitHub Actions** — см. шаг 3.

Скрипт можно запускать повторно: сделанные шаги он пропускает, `.env` не перезаписывает.

## Шаг 3. Секреты в GitHub (после bootstrap, 5 минут)

GitHub → репозиторий → Settings → Secrets and variables → Actions → New repository secret:

| Секрет | Значение |
|---|---|
| `DEPLOY_SSH_HOST` | домен или IP сервера |
| `DEPLOY_SSH_KEY` | приватный ключ из вывода bootstrap — целиком, от `-----BEGIN` до `-----END…-----` (он же в `/srv/tuc/.actions_key`) |

Необязательные: `DEPLOY_SSH_USER` (по умолчанию `deploy`), `DEPLOY_SSH_PORT` (22),
`STAGING_SSH_HOST` — если когда-нибудь тестовый стенд переедет на отдельный сервер.

Проверка: workflow «Deploy» запускается сам после зелёного CI, кнопки «Run workflow» у него нет —
дождитесь следующего пуша в `dev` (ночная сборка) или сделайте любой коммит в `dev`. В логе job
`deploy` должно быть «Стенд staging ← ветка dev …» и «staging готов». Пока секретов нет, job пишет
«деплой не настроен» и завершается успешно.

## Шаг 4. Токены и ключи в `.env` стендов

`.env` стенда — `/srv/tuc/prod/.env` и `/srv/tuc/staging/.env` (редактировать под `deploy`:
`ssh deploy@<IP>`, `nano /srv/tuc/prod/.env`). После правки — перезапуск стенда:

```bash
cd /srv/tuc/prod && docker compose up -d
```

Что вписать — в `docs/STATUS.md`, раздел «Нужно от владельца» (Telegram, ЮKassa, позже Google).
Важно про два стенда:

- **Telegram**: один токен нельзя использовать на двух стендах одновременно — Telegram отдаёт обновления
  только одному. Для staging либо заведите второго бота в @BotFather, либо оставьте `TELEGRAM_BOT_TOKEN`
  на staging пустым (тогда сервис `bot` там сам завершится, уведомлений не будет).
- **ЮKassa**: на staging — ключи тестового магазина (`test_…`), на prod — боевые (`live_…`).
  Адрес HTTP-уведомлений в кабинете ЮKassa: `https://<домен>/api/v1/payments/yookassa/webhook`.
- `SITE_URL` уже выставлен в `https://<домен>` — его используют ссылки в Telegram и возврат с оплаты.

## Как это живёт дальше

- **Пуш в `dev`** → CI → staging обновился (2–5 минут). Утром проверяете `https://staging.<домен>`.
- **PR `dev` → `main`, слияние** → CI → prod обновился. Миграции БД применяются сами при старте api.
- **Посмотреть, что происходит**: `ssh deploy@<IP>`, затем

  ```bash
  cd /srv/tuc/prod
  docker compose ps                 # состояние контейнеров (api должен быть healthy)
  docker compose logs -f api        # логи API; так же: web, worker, bot, postgres
  cd /srv/tuc/prod/deploy/edge && docker compose logs -f caddy   # общий Caddy живёт отдельно
  ```

- **Развернуть руками** (например, после правки `.env`): `bash /srv/tuc/prod/deploy/deploy.sh`.
- **Откатиться** на старый коммит: `bash /srv/tuc/prod/deploy/deploy.sh <hash коммита>`
  (следующий деплой из Actions снова поставит последний коммит `main`).
- **Бэкап** БД прода: каждую ночь в 03:15 в `/srv/tuc/backups/prod-ГГГГ-ММ-ДД.sql.gz`, 14 дней.
  Восстановить: `zcat файл.sql.gz | docker compose exec -T postgres psql -U tuc -d tuc`.
  Папку с моделями `/srv/tuc/prod/data/` бэкап не трогает — при переезде копируйте её отдельно.
- **Цены и профили** (`config/pricing.yaml`, `profiles/`) правятся в репозитории и приезжают деплоем.
  На сервере файлы репозитория не править: `deploy.sh` делает `git reset --hard`, правки пропадут.
- **SQL к базе прода** с сервера: `docker compose exec postgres psql -U tuc -d tuc`.
- **Google-таблица учёта** (B11): worker каждую ночь в 05:05 МСК переписывает лист «Заказы (сайт)».
  Ключ сервисного аккаунта положить в `/srv/tuc/prod/secrets/google-sa.json` (`chmod 600`, папка в
  `.gitignore`, в контейнер видна как `/srv/secrets/`), в `.env`: `GOOGLE_SA_JSON_PATH=/srv/secrets/google-sa.json`
  и `GOOGLE_SHEET_ID=<id из адреса таблицы>`, затем `docker compose up -d`. Выгрузить сейчас, не дожидаясь ночи:
  `docker compose exec api python -m app.sheets` (ошибки доступа он объясняет словами). Логи ночных выгрузок:
  `docker compose logs worker | grep Google`.
- **Superset / DBeaver / pandas к базе** (B11): один раз на стенде `bash /srv/tuc/prod/deploy/readonly-user.sh` —
  создаст пользователя `tuc_ro` (только SELECT, в том числе для будущих таблиц) и запишет пароль в `.env`
  (`POSTGRES_RO_PASSWORD`). Postgres снаружи виден только на `127.0.0.1` сервера (prod — порт 5433, staging — 5434),
  поэтому с ноутбука открываете SSH-туннель `ssh -N -L 5433:127.0.0.1:5433 deploy@<домен>` и подключаетесь к
  `127.0.0.1:5433`, база `tuc`, пользователь `tuc_ro`. В Superset — «+ Database → PostgreSQL», тот же адрес
  (если Superset в Docker на ноутбуке — вместо `127.0.0.1` укажите `host.docker.internal`).
- **Добавить второй домен / сменить домен**: поправить `/srv/tuc/prod/deploy/edge/.env`
  и выполнить `bash /srv/tuc/prod/deploy/edge/render-sites.sh`.

## Если что-то не так

| Симптом | Куда смотреть |
|---|---|
| Сайт не открывается, в браузере ошибка сертификата | DNS указывает не туда, или порт 80/443 закрыт у хостера. `cd /srv/tuc/prod/deploy/edge && docker compose logs caddy` — Caddy пишет, почему не выдали сертификат. |
| 502 Bad Gateway | Контейнер стенда не поднялся: `docker compose ps`, `docker compose logs api` (или `web`). |
| Job «Deploy» красный: `Permission denied (publickey)` | В `DEPLOY_SSH_KEY` не тот ключ или вставлен не целиком. Ключ — `/srv/tuc/.actions_key` на сервере. |
| Job «Deploy» красный: `api не поднялся` | В логе job — последние 50 строк логов api. Чаще всего ошибка в `.env` или упавшая миграция. |
| Кончилось место | `docker system df`, `docker image prune -a`, старые бэкапы в `/srv/tuc/backups`, `du -sh /srv/tuc/*/data`. |
| Всё сломалось, надо с нуля | Остановить стенд `docker compose down` (БД в volume `tuc-prod_pgdata` останется), запустить `bootstrap.sh` снова — он восстановит недостающее. |
