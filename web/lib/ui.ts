/**
 * Дизайн-система BroPrint (B40) — чистые функции без React: какие CSS-классы у кнопки,
 * бейджа и т. п. Сами классы описаны в app/globals.css, компоненты — components/ui/.
 * Здесь всё, что можно проверить тестами без браузера (lib/ui.test.ts).
 */

import type { OrderStatus } from "./order";

/** Склеивает классы, пропуская пустые: cx("btn", cond && "btn-sm") → "btn btn-sm". */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter((p): p is string => typeof p === "string" && p.trim() !== "").join(" ");
}

export type ButtonVariant = "primary" | "secondary" | "ghost";
export type ButtonSize = "md" | "sm";

/** Классы кнопки: вариант (оранжевая / с рамкой / без фона) и размер. */
export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md", extra?: string): string {
  return cx("btn", `btn-${variant}`, size === "sm" && "btn-sm", extra);
}

export type BadgeTone = "neutral" | "active" | "success" | "danger";

/** Классы бейджа по тону. */
export function badgeClass(tone: BadgeTone = "neutral", extra?: string): string {
  return cx("badge", `badge-${tone}`, extra);
}

/**
 * Тон бейджа для статуса заказа. По брендбуку зелёный — только «Готов» и «Выдан»;
 * «Печатается» и «Оплачен» — оранжевый «в работе»; «Принят» — нейтральный; «Отменён» — красный.
 */
export const STATUS_TONES: Record<OrderStatus, BadgeTone> = {
  new: "neutral",
  paid: "active",
  printing: "active",
  ready: "success",
  done: "success",
  cancelled: "danger",
};

export function statusTone(status: OrderStatus): BadgeTone {
  return STATUS_TONES[status] ?? "neutral";
}

/** Тема сайта: светлая, тёмная или «как в системе» (атрибут data-theme не ставим). */
export type Theme = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "bp-theme";

/** Что лежит в localStorage → тема. Мусор и пустота = «как в системе». */
export function parseTheme(raw: string | null | undefined): Theme {
  return raw === "light" || raw === "dark" ? raw : "system";
}

/** Какую тему включить по клику: светлая ↔ тёмная; из «как в системе» — противоположную системной. */
export function nextTheme(current: Theme, systemDark: boolean): Theme {
  if (current === "system") return systemDark ? "light" : "dark";
  return current === "dark" ? "light" : "dark";
}

/** Какая тема сейчас на экране с учётом системной настройки. */
export function effectiveTheme(theme: Theme, systemDark: boolean): "light" | "dark" {
  if (theme === "system") return systemDark ? "dark" : "light";
  return theme;
}

/**
 * Скрипт для <head>: ставит data-theme на <html> до первой отрисовки, чтобы страница не мигала
 * светлым при тёмной теме. Одна строка, без зависимостей; ключ localStorage — THEME_STORAGE_KEY.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t);}catch(e){}})();`;
