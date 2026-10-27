# Аналитика: воронка и таблица `events`

Сервер пишет в таблицу `events` по строке на каждый шаг клиентского пути (B12).
Никакого JS-трекинга на сайте нет — считается только то, что реально произошло на сервере.
Сводка за 30 дней видна в админке над списком заказов; всё остальное — SQL ниже
(подключение read-only пользователем `tuc_ro` — см. `docs/DEPLOY.md`, раздел про Superset).

## Шаги воронки

| `name` | Когда пишется | Ключ шага | Что в `props` |
|---|---|---|---|
| `upload` | клиент загрузил модель, файл принят и проверен — или нажал «Заказать» в каталоге (B20) или в редакторе (B21) | `upload_id` | `ext`, `size_bytes`, `watertight`, `warnings`; у модели из каталога ещё `source = "catalog"` и `catalog_slug`; из редактора — `source = "editor"`, `editor_slug`, `build_id`; у модели с тиснением (B30) — `source = "emboss"`, `parent_upload_id` (исходная загрузка), `job_id`, `kind` (text / logo), `style` (raised / engraved) |
| `editor_build` | клиент нажал «Построить модель» в редакторе (B21) — ещё до загрузки, поэтому не шаг воронки и в сводке админки не показывается | — (`props.build_id`) | `editor_slug`, `build_id`, `params`, `cached` (true — такие параметры уже строили, OpenSCAD не запускался) |
| `emboss_build` | клиент нажал «Нанести» на странице модели (B30) — тиснение надписи/логотипа; как и `editor_build`, не шаг воронки | `upload_id` (исходная загрузка; `props.job_id`) | `job_id`, `cached`, `params` (kind, text, font, bold, size_mm, depth_mm, style, face, dx, dy, angle) |
| `paint_build` | клиент нажал «Собрать модель в цветах» на странице модели (B31) — раскраска по частям; не шаг воронки | `upload_id` (исходная загрузка; `props.job_id`) | `job_id`, `cached`, `parts` (сколько деталей), `colors` (сколько разных цветов) |
| `account_login` | клиент вошёл в кабинет по коду из письма (B32); не шаг воронки, ключей нет — считаем только факт и время (кто вошёл — в `client_sessions`) | — | — |
| `quote` | посчитана цена (`POST /uploads/{id}/quote`) | `upload_id`, `quote_id` | `material`, `supports`, `qty`, `postprocess`, `delivery`, `total` |
| `order` | заказ создан (в той же транзакции, что строка в `orders`) | `upload_id`, `quote_id`, `order_id` | `total`, `delivery`, `qty`, `payment_method` (`online` — карта через ЮKassa, `invoice` — по счёту), `b2b` (true — заказ от организации или ИП, B33) |
| `payment_started` | клиент нажал «Оплатить», платёж в ЮKassa создан | `upload_id`, `order_id` | `amount`, `yookassa_id` |
| `paid` | ЮKassa подтвердила оплату (один раз, повторные вебхуки не дублируют) | `upload_id`, `order_id` | `amount`, `yookassa_id` |

Как шаги склеиваются в один путь: `upload → quote → order` — по `upload_id`
(одна загрузка = одна модель = один путь), `order → payment_started → paid` — по `order_id`.
У заказа `upload_id` тоже заполнен, так что весь путь можно собрать по одному `upload_id`.

Чего в воронке нет: отклонённые загрузки (не тот формат, больше 100 МБ, битая сетка),
расчёт печати (слайсинг) как отдельный шаг, просмотры страниц. Повторные расчёты по одной
модели (поменял материал/тираж) — это несколько строк `quote` с одним `upload_id`:
в воронке считайте уникальные `upload_id`, а не строки.

Оплата наличными при самовывозе (владелец ставит «оплачен» руками в боте или админке)
событием `paid` **не считается** — `paid` только про онлайн-оплату. Для «все оплаченные»
смотрите `orders.status`.

Таблица только дописывается: строки не меняются и не удаляются; внешнего ключа на `orders` нет,
чтобы журнал пережил удаление заказа. Время — `created_at`, UTC (в SQL ниже переводится в МСК).

## Готовые запросы

Воронка по неделям (уникальные модели на каждом шаге и конверсии):

```sql
with steps as (
  select date_trunc('week', created_at at time zone 'Europe/Moscow')::date as week,
         count(distinct upload_id) filter (where name = 'upload') as uploads,
         count(distinct upload_id) filter (where name = 'quote')  as quotes,
         count(distinct upload_id) filter (where name = 'order')  as orders,
         count(distinct order_id)  filter (where name = 'paid')   as paid
  from events
  group by 1
)
select week, uploads, quotes, orders, paid,
       round(100.0 * quotes / nullif(uploads, 0), 1) as "quote %",
       round(100.0 * orders / nullif(quotes, 0), 1)  as "order %",
       round(100.0 * paid   / nullif(orders, 0), 1)  as "paid %"
from steps
order by week desc;
```

Где теряем: модели, по которым посчитали цену, но не заказали, с последней ценой:

```sql
select q.upload_id,
       max(q.created_at at time zone 'Europe/Moscow') as last_quote_msk,
       count(*) as quotes,
       (array_agg(q.props->>'total' order by q.created_at desc))[1]::int as last_total,
       (array_agg(q.props->>'material' order by q.created_at desc))[1] as last_material
from events q
where q.name = 'quote'
  and not exists (select 1 from events o where o.name = 'order' and o.upload_id = q.upload_id)
group by q.upload_id
order by last_quote_msk desc;
```

Сколько времени проходит от загрузки до заказа (медиана, минуты):

```sql
select percentile_cont(0.5) within group (
         order by extract(epoch from (o.created_at - u.created_at)) / 60
       ) as median_minutes
from events u
join events o on o.upload_id = u.upload_id and o.name = 'order'
where u.name = 'upload';
```

Распределение расчётов по материалам и тиражам за месяц:

```sql
select props->>'material' as material,
       case when (props->>'qty')::int = 1 then '1'
            when (props->>'qty')::int <= 10 then '2–10' else '11+' end as qty_bucket,
       count(*) as quotes,
       round(avg((props->>'total')::numeric)) as avg_total
from events
where name = 'quote' and created_at >= now() - interval '30 days'
group by 1, 2
order by 1, 2;
```

Начали платить, но не заплатили (повод написать клиенту):

```sql
select o.id as order_id, o.customer_name, o.phone, o.total,
       s.created_at at time zone 'Europe/Moscow' as started_msk
from events s
join orders o on o.id = s.order_id
where s.name = 'payment_started'
  and o.status = 'new'
  and not exists (select 1 from events p where p.name = 'paid' and p.order_id = s.order_id)
order by s.created_at desc;
```

## Добавить новый шаг

1. Имя — в `EVENT_NAMES` (`api/app/models.py`), с комментарием, когда он случается.
2. В нужном месте кода — `track("имя", upload_id=…, order_id=…, props={…})` (`api/app/events.py`).
   Если под рукой есть сессия БД — передать `db=db`, событие уедет одной транзакцией с основной записью.
3. Строку в таблицу выше и, если шаг нужен в сводке админки, — в `FUNNEL_KEY` и шаблон `admin/orders.html`.

## Каталог против своих моделей (B20)

```sql
-- Сколько загрузок и заказов пришло из каталога, а сколько — по своим файлам, за 30 дней.
select coalesce(e.props->>'source', 'own') as source,
       count(distinct e.upload_id) as uploads,
       count(distinct o.upload_id) as orders
from events e
left join events o on o.upload_id = e.upload_id and o.name = 'order'
where e.name = 'upload' and e.created_at > now() - interval '30 days'
group by 1;

-- Какие модели каталога заказывают чаще.
select e.props->>'catalog_slug' as model, count(*) as orders
from events e
join events o on o.upload_id = e.upload_id and o.name = 'order'
where e.name = 'upload' and e.props->>'source' = 'catalog'
group by 1 order by 2 desc;
```

## Редакторы (B21)

```sql
-- Сколько раз строили модель в каждом редакторе и сколько из этого дошло до загрузки и заказа, за 30 дней.
-- Сборку и загрузку связывает build_id: он есть в props у editor_build и у upload из редактора.
with builds as (
  select props->>'editor_slug' as editor, props->>'build_id' as build_id, count(*) as clicks
  from events
  where name = 'editor_build' and created_at > now() - interval '30 days'
  group by 1, 2
)
select b.editor,
       sum(b.clicks) as builds,
       count(distinct u.upload_id) as uploads,
       count(distinct o.upload_id) as orders
from builds b
left join events u on u.name = 'upload' and u.props->>'build_id' = b.build_id
left join events o on o.name = 'order' and o.upload_id = u.upload_id
group by 1 order by 2 desc;

-- Какие параметры выбирают чаще (пример для редактора spacer: внешний диаметр).
select props->'params'->>'outer_d' as outer_d, count(*) as builds
from events
where name = 'editor_build' and props->>'editor_slug' = 'spacer'
group by 1 order by 2 desc limit 20;
```

## Тиснение (B30)

```sql
-- Сколько раз наносили надпись/логотип и сколько таких моделей дошло до заказа, за 30 дней.
-- Нажатие «Нанести» (emboss_build) и новую загрузку (upload, source = emboss) связывает job_id.
with builds as (
  select props->'params'->>'kind' as kind, props->'params'->>'style' as style,
         props->>'job_id' as job_id, count(*) as clicks
  from events
  where name = 'emboss_build' and created_at > now() - interval '30 days'
  group by 1, 2, 3
)
select b.kind, b.style,
       sum(b.clicks) as clicks,
       count(distinct u.upload_id) as models,
       count(distinct o.upload_id) as orders
from builds b
left join events u on u.name = 'upload' and u.props->>'source' = 'emboss' and u.props->>'job_id' = b.job_id
left join events o on o.name = 'order' and o.upload_id = u.upload_id
group by 1, 2 order by 3 desc;

-- На какую грань наносят чаще.
select props->'params'->>'face' as face, count(*) as clicks
from events where name = 'emboss_build'
group by 1 order by 2 desc;
```

## Раскраска по частям (B31)

```sql
-- Сколько раз собирали модель в цветах и сколько таких моделей дошло до заказа, за 30 дней.
-- Нажатие (paint_build) и новую загрузку (upload, source = paint) связывает job_id;
-- в upload.props: parts — сколько деталей, colors — сколько разных цветов.
with builds as (
  select props->>'job_id' as job_id, (props->>'colors')::int as colors, count(*) as clicks
  from events
  where name = 'paint_build' and created_at > now() - interval '30 days'
  group by 1, 2
)
select b.colors,
       sum(b.clicks) as clicks,
       count(distinct u.upload_id) as models,
       count(distinct o.upload_id) as orders
from builds b
left join events u on u.name = 'upload' and u.props->>'source' = 'paint' and u.props->>'job_id' = b.job_id
left join events o on o.name = 'order' and o.upload_id = u.upload_id
group by 1 order by 1;

-- Какие цвета выбирают: заказы по раскрашенным моделям, снимок расчёта хранит сводку словами.
select quote->>'decor' as decor, count(*) as orders
from orders
where quote->>'decor' is not null
group by 1 order by 2 desc;
```

## Кабинет клиента (B32)

```sql
-- Сколько клиентов заходили в кабинет за 30 дней и сколько заказов они потом оформили.
-- Входы — события account_login (без ключей); «после входа» — заказы с e-mail, у которого
-- есть живая или истёкшая сессия, созданная раньше заказа.
select count(*) filter (where name = 'account_login') as logins
from events
where created_at > now() - interval '30 days';

select o.id, o.email, o.total, o.created_at at time zone 'Europe/Moscow' as created_msk
from orders o
where exists (select 1 from client_sessions s
              where s.email = lower(o.email) and s.created_at < o.created_at)
  and o.created_at > now() - interval '30 days'
order by o.id desc;

-- Повторные клиенты: адреса, с которых оформлено больше одного заказа (кабинет ищет заказы так же — по e-mail).
select lower(email) as email, count(*) as orders, sum(total) as total_rub
from orders
where email is not null
group by lower(email)
having count(*) > 1
order by orders desc;
```

## B2B — заказы организаций (B33)

```sql
-- Доля и деньги заказов от организаций за 30 дней. Юрлицо — у заказа заполнен company_name,
-- такие заказы платят по счёту (payment_method = 'invoice'); «оплачен» ставит владелец вручную.
select payment_method,
       count(*) as orders,
       sum(total) as total_rub,
       round(avg(qty)) as avg_qty,
       count(*) filter (where status in ('paid', 'printing', 'ready', 'done')) as paid_orders
from orders
where created_at > now() - interval '30 days'
group by payment_method;

-- Кто из организаций заказывает чаще всего (по ИНН — название могли написать по-разному).
select company_inn, max(company_name) as company, count(*) as orders, sum(total) as total_rub,
       max(created_at) at time zone 'Europe/Moscow' as last_order_msk
from orders
where company_inn is not null
group by company_inn
order by total_rub desc;

-- Счета, которые ждут оплаты дольше 5 дней — повод напомнить бухгалтерии.
select id, company_name, email, total, created_at at time zone 'Europe/Moscow' as created_msk
from orders
where payment_method = 'invoice' and status = 'new'
  and created_at < now() - interval '5 days'
order by created_at;
```
