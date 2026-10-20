/**
 * Главная страница (B14): тексты блоков и помощники, которые превращают прайс
 * (GET /api/v1/pricing) в строки для лендинга. Цены берутся из config/pricing.yaml —
 * владелец правит yaml, главная обновляется сама (через ISR, раз в 10 минут).
 */

import { formatPrice } from "./format";
import type { Pricing } from "./pricing";

/** Шаги «как это работает» — те же, что на /about, но короче. */
export const STEPS: { title: string; text: string }[] = [
  { title: "Загрузите модель", text: "STL или 3MF до 100 МБ. Сайт проверит сетку и покажет модель в 3D." },
  { title: "Получите цену", text: "Сервер сам посчитает время печати и расход пластика. Цена — за минуту, с разложением по строкам." },
  { title: "Оформите и оплатите", text: "Материал, тираж, самовывоз или курьер. Оплата картой онлайн." },
  { title: "Заберите изделие", text: "Статус заказа — по ссылке: принят → оплачен → печатается → готов." },
];

/** Преимущества — без выдуманных фактов (лет на рынке, число принтеров). */
export const BENEFITS: { title: string; text: string }[] = [
  { title: "Цена до заказа", text: "Считает сервер, а не менеджер: видно, сколько стоит пластик, работа принтера и доставка." },
  { title: "Без переписки", text: "Загрузили, выбрали материал, оплатили — заказ сразу в работе, статус по ссылке." },
  { title: "Проверка модели", text: "Дыры в сетке, дюймы вместо миллиметров, не влезает в принтер — скажем до оплаты." },
  { title: "Тиражи дешевле", text: "Скидка за количество считается автоматически — от 10 штук и от 50." },
];

/** Описания материалов для карточек. Ключ — имя из pricing.yaml / profiles/filament. */
export const MATERIAL_INFO: Record<string, { tagline: string; text: string }> = {
  PLA: { tagline: "точный и недорогой", text: "Макеты, корпуса, декор. Много цветов. Не любит жару выше 50 °C." },
  PETG: { tagline: "прочный, терпит влагу", text: "Функциональные детали, крепления, ёмкости. До 70 °C." },
  ABS: { tagline: "ударопрочный, до 90 °C", text: "Детали для авто и техники. Шлифуется, обрабатывается ацетоном." },
};

export type MaterialCard = { name: string; tagline: string; text: string; price: string | null };

/** Карточки материалов из прайса: имя, описание, «от 4 ₽/г». Без прайса — описания без цен. */
export function materialCards(pricing: Pricing | null): MaterialCard[] {
  const names = pricing ? Object.keys(pricing.materials) : Object.keys(MATERIAL_INFO);
  return names.map((name) => {
    const info = MATERIAL_INFO[name] ?? { tagline: "", text: "Подробности — при расчёте цены." };
    const perG = pricing?.materials[name]?.price_per_g;
    return {
      name,
      tagline: info.tagline,
      text: info.text,
      price: perG === undefined ? null : `от ${formatPerGram(perG)}/г`,
    };
  });
}

/** 4 → «4 ₽», 4.5 → «4,5 ₽» — цена за грамм без лишних нулей. */
export function formatPerGram(rub: number): string {
  const rounded = Math.round(rub * 100) / 100;
  return `${String(rounded).replace(".", ",")} ₽`;
}

/** Подзаголовок про минимальный заказ: «Минимальный заказ — 500 ₽». Без прайса — пусто. */
export function minOrderText(pricing: Pricing | null): string | null {
  if (!pricing || pricing.min_order <= 0) return null;
  return `Минимальный заказ — ${formatPrice(pricing.min_order)}`;
}

/** Адрес API для серверного рендера (внутри docker — http://api:8000). */
export function apiInternalUrl(): string {
  return process.env.API_INTERNAL_URL ?? "http://localhost:8000";
}

/**
 * Прайс для главной. Ходит в API с сервера Next; если API недоступен (сборка образа,
 * dev без uvicorn) — null, и страница рендерится без цен, а не падает.
 */
export async function loadPricing(): Promise<Pricing | null> {
  try {
    const r = await fetch(`${apiInternalUrl()}/api/v1/pricing`, { next: { revalidate: 600 } });
    if (!r.ok) return null;
    return (await r.json()) as Pricing;
  } catch {
    return null;
  }
}
