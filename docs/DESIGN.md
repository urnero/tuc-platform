# Дизайн BroPrint — для сайта

Источник — брендбук владельца (артефакт «BroPrint», тип Design System). Копия токенов — `docs/brand-tokens.json`. Логотипы — `web/public/brand/`. Менять палитру — только там и здесь.

## Суть бренда

Семейная мастерская 3D-печати, два брата. Слоган: **Воплотим любую идею в жизнь.** Подпись к логотипу: **Семейная мастерская 3D-печати.** Образ: графит станка, тёплый песок, один яркий цвет пластика. Голос: «мы», на «вы», короткие фразы, сначала факт (срок, материал, цена). Без капслока, без восклицаний, не больше одного эмодзи.

Название пишем **BroPrint** (одно слово, B и P заглавные). В `<title>`, подвале и описаниях добавляем «БроПринт» для поиска по-русски. Старое имя ТУЦ на сайте не показываем.

## Цвета (светлая / тёмная)

| Токен | Светлая | Тёмная | Где |
|---|---|---|---|
| `filament` | #F26A1B | #F26A1B | Акцент: кнопка действия, верхний слой знака, полосы паттерна. ≤10 % площади. |
| `on-filament` | #1C1D1F | #1C1D1F | Текст на оранжевом. Белый на оранжевом не используем. |
| `filament-text` | #B4460A | #FF8A45 | Оранжевый текст и ссылки на фоне. |
| `graphite` | #1C1D1F | #34373C | Тёмные плашки, нижний слой знака. |
| `steel` | #3E5566 | #8FA9BB | Вторичный: иконки, полосы паттерна, второстепенные плашки. |
| `sand` | #E8DCC8 | #3A332A | Фон карточек с изделиями, подложка фото. |
| `surface` | #F5F2EC | #17181A | Фон страницы. |
| `surface-raised` | #FFFFFF | #222326 | Карточки и плашки. |
| `ink` | #1C1D1F | #F3EFE7 | Основной текст. |
| `ink-muted` | #5E5A53 | #A9A49B | Подписи, второстепенный текст. |
| `line` | #D9D3C8 | #34353A | Разделители и рамки карточек (не для полей ввода). |
| `success` | #2F7D4F | #5CC08A | Только статус «Готово»/«Выдан». |

Пропорция: 60 % surface/graphite · 30 % sand/steel · 10 % filament.

В `web/app/globals.css` токены объявляются на `:root` (светлая), переопределяются в `@media (prefers-color-scheme: dark)` под `:root:not([data-theme="light"])` и в `:root[data-theme="dark"]`. Переключатель темы в шапке пишет `data-theme` и `localStorage`. Старые переменные `--bg/--fg/--muted/--accent` остаются как алиасы: `--bg: var(--surface)` и т. д., чтобы не ломать существующие страницы.

## Шрифты

- **Unbounded 700** — заголовки h1/h2, цифры цены на главной, слоганы. Не длиннее двух строк.
- **Manrope 400–600** — весь остальной текст.
- Оба из npm: `@fontsource-variable/manrope`, `@fontsource/unbounded` (вес 700). Не с Google Fonts — сборка идёт на сервере в РФ.

| Стиль | Размер/интерлиньяж | Вес | Где |
|---|---|---|---|
| display | 56/60, −0.02em (телефон 36/40) | Unbounded 700 | первый экран главной |
| heading | 32/38, −0.01em (телефон 26/32) | Unbounded 700 | заголовки разделов |
| title | 20/26 | Unbounded 600 | названия карточек и изделий |
| lead | 18/28 | Manrope 500 | подзаголовки |
| body | 16/24 | Manrope 400 | текст |
| caption | 13/18, +0.02em | Manrope 600 | параметры печати: `PETG · 0,2 мм · 4 часа` |

## Отступы и радиусы

- Шаг 4 px: `space-1` 4, `space-2` 8, `space-4` 16, `space-6` 24, `space-10` 40.
- `radius-sm` 4 px — метки, поля ввода. `radius-md` 12 px — карточки, кнопки, фото. `radius-pill` — полосы паттерна «Слои».
- Кнопка действия: фон `filament`, текст `on-filament`, радиус `radius-md`, высота 44 px на телефоне.

## Логотип

`web/public/brand/`: `broprint-lockup.svg` (знак + надпись, светлый фон), `broprint-lockup-light.svg` (тёмный фон), `broprint-mark*.svg` (знак для фавикона, аватаров), `broprint-wordmark*.svg`. Охранное поле — `space-6`. Минимум: знак 24 px, знак с надписью 120 px по ширине. Нельзя: менять цвета слоёв, растягивать, тени, обводки, градиенты. Фавикон — `broprint-mark.svg` (и PNG 32/180 из него).

## Паттерн «Слои»

Горизонтальные полосы-пилюли `filament`, `sand`, `steel` на `graphite`. Уходят за край. Не больше 40 % макета, не под текстом. На сайте — фон первого экрана и пустых состояний, рисуется CSS/SVG, не картинкой.

## Фото

Только реальные изделия и процесс, тёплый свет, фон песок/графит/верстак. Без стока. Пока фото нет — заглушка на `sand` с контуром знака.

## Как это сделано на сайте (B40)

- Токены — `web/app/globals.css`: `:root` (светлая), `@media (prefers-color-scheme: dark)` под `:root:not([data-theme="light"])` и `:root[data-theme="dark"]`. Те же токены отданы Tailwind через `@theme inline`, поэтому работают утилиты `bg-filament`, `text-ink-muted`, `border-line`, `font-display`, `hover:bg-sand` и т. д. База (шрифты заголовков) и компоненты лежат в `@layer base` / `@layer components`, чтобы утилиты Tailwind могли их переопределять.
- Алиасы `--bg/--fg/--muted/--accent` → `surface/ink/ink-muted/filament-text`; все страницы до B40 переведены на токены напрямую (`var(--ink-muted)` и т. п.), кнопки действия — `var(--filament)` + `var(--on-filament)`.
- Добавлен токен `--danger` (ошибки форм, статус «Отменён»): в брендбуке его нет, светлая `#B3261E`, тёмная `#FF7B72` (запись в DECISIONS.md).
- Шрифты — `app/layout.tsx` импортирует `@fontsource/unbounded/700.css` и `@fontsource-variable/manrope` (семейство в CSS — `"Manrope Variable"`). Заголовки `h1/h2/h3` — Unbounded через базовые стили; классы `.t-display .t-heading .t-title .t-lead .t-caption` — для текста, который не заголовок.
- Компоненты — `web/components/ui/` (`import { Button, Card, Field, Select, StatusBadge, Logo, ThemeToggle } from "@/components/ui"`). CSS-классы те же, что у компонентов, их можно писать и руками: `.btn .btn-primary|secondary|ghost .btn-sm`, `.card .card-sand`, `.field` (input/select/textarea), `.badge .badge-neutral|active|success|danger`, `.layers` (паттерн «Слои»). Чистая логика (классы, тон статуса, тема) — `web/lib/ui.ts` с тестами.
- Тема: `ThemeToggle` в шапке пишет `data-theme` на `<html>` и `localStorage["bp-theme"]`; скрипт `THEME_INIT_SCRIPT` в `<head>` ставит атрибут до первой отрисовки (без мигания). Без выбора — как в системе.
- Шапка `components/SiteHeader.tsx` (логотип-lockup, ссылки с `lg`, переключатель, кнопка; бургер-меню — `components/MobileMenu.tsx`), подвал `components/SiteFooter.tsx` (знак, слоган, разделы, документы, контакты). Логотип — `components/ui/Logo.tsx`: показывает обычный файл или `*-light.svg` по теме через классы `.logo-light/.logo-dark`.
- Фавикон — `web/app/icon.svg` (копия знака) и `web/app/apple-icon.png` (180×180, знак на `surface`), Next подключает их сам. Цвет адресной строки — `viewport.themeColor` в layout.
