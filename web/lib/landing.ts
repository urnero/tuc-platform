/**
 * Главная страница (B14, воронка — B41): тексты блоков и помощники, которые превращают прайс
 * (GET /api/v1/pricing) в строки для лендинга. Цены берутся из config/pricing.yaml —
 * владелец правит yaml, главная обновляется сама (через ISR, раз в 10 минут).
 *
 * Что править владельцу: STUDIO (рассказ о мастерской и срок), FACTS (парк принтеров —
 * должен совпадать с docs/PRINTERS.md), FAQ (вопросы-ответы). Всё остальное считается само.
 */

import { formatPrice } from "./format";
import type { MaterialItem, MaterialsResponse } from "./materials";
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

/**
 * Запасные описания материалов — на случай, если API не отдал справочник (B44).
 * Основной источник — config/materials.yaml (GET /api/v1/materials).
 */
export const MATERIAL_INFO: Record<string, { tagline: string; text: string }> = {
  PLA: { tagline: "точный и недорогой", text: "Макеты, корпуса, декор. Много цветов. Не любит жару выше 50 °C." },
  PETG: { tagline: "прочный, терпит влагу", text: "Функциональные детали, крепления, ёмкости. До 70 °C." },
  ABS: { tagline: "ударопрочный, до 90 °C", text: "Детали для авто и техники. Шлифуется, обрабатывается ацетоном." },
};

export type MaterialCard = {
  name: string;
  tagline: string;
  text: string;
  price: string | null;
  onRequest?: boolean;
};

/**
 * Карточки материалов: имя, описание, «от 4 ₽/г».
 * Есть справочник (B44) — карточки по нему (смолы — «цена по запросу»); нет — по прайсу и
 * запасным описаниям. Без прайса — описания без цен.
 */
export function materialCards(pricing: Pricing | null, items: MaterialItem[] = []): MaterialCard[] {
  if (items.length) {
    return items.map((item) => {
      const perG = pricing?.materials[item.key]?.price_per_g;
      let price: string | null = perG === undefined ? null : `от ${formatPerGram(perG)}/г`;
      if (item.on_request) price = "цена по запросу";
      return { name: item.name, tagline: item.tagline, text: item.hint, price, onRequest: item.on_request };
    });
  }
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

/**
 * Рассказ о мастерской для блока доверия. Срок — обещание владельца, не расчёт сервера:
 * поправить, если реальный срок другой (часы печати конкретной модели клиент видит в расчёте).
 */
export const STUDIO = {
  title: "Два брата, своя мастерская",
  text:
    "Печатаем сами, на своих принтерах в Москве. Файл смотрим перед печатью, а не после: если модель " +
    "не влезает, тонкая или с дырами в сетке — скажем до оплаты и подскажем, что поправить.",
  /** Срок для небольших деталей — то, что обещаем на главной и в FAQ. */
  leadTime: "Небольшие детали обычно готовы через 1–3 дня, тираж и крупные — по расчёту.",
};

/**
 * Факты о парке — из docs/PRINTERS.md (7 FDM-принтеров + 1 SLA, максимум 256 мм на P1S,
 * до 4 цветов у P1S/Kobra 3, закрытые камеры у P1S и Q1 Pro). При смене парка править здесь и там.
 */
export const FACTS: { value: string; label: string }[] = [
  { value: "8", label: "принтеров: 7 FDM и 1 SLA — тираж печатаем параллельно" },
  { value: "256 мм", label: "максимальный размер детали по каждой стороне; крупнее — частями" },
  { value: "4 цвета", label: "за одну печать — многоцветные детали без склейки" },
  { value: "2", label: "принтера с закрытой камерой — для ABS, PC и нейлона" },
];

/** Вопросы и ответы (5–7). Текст без выдуманных фактов: сроки — из STUDIO, цены — из прайса. */
export const FAQ: { q: string; a: string }[] = [
  {
    q: "Какой файл нужен?",
    a: "STL или 3MF до 100 МБ, размеры в миллиметрах. Файл из Tinkercad, Fusion, Blender или скачанный с Thingiverse / Printables подходит. Нет файла — выберите модель в каталоге или задайте размеры в редакторе, файл построится сам.",
  },
  {
    q: "Сколько это стоит?",
    a: "Цена = граммы пластика × цена за грамм + часы печати × ставка принтера. Сервер считает её сам за минуту после загрузки и показывает разложение по строкам. Расчёт ни к чему не обязывает.",
  },
  {
    q: "Как быстро будет готово?",
    a: STUDIO.leadTime + " Часы печати вашей модели видны в расчёте — по ним понятно, когда ждать.",
  },
  {
    q: "Какой материал выбрать?",
    a: "PLA — для макетов, декора и всего, что не греется. PETG — для функциональных деталей: прочнее, терпит влагу и до 70 °C. ABS — ударопрочный, до 90 °C, для авто и техники. TPU — гибкий, как резина. Нейлон, поликарбонат и пластики с углеволокном — для нагруженных деталей. Смола — для миниатюр и мелких деталей, её цену называем по заявке. Под выбором материала на странице расчёта есть подсказка «когда какой».",
  },
  {
    q: "Можно напечатать большую деталь?",
    a: "До 256 мм по каждой стороне целиком. Крупнее — печатаем частями под склейку или по запросу: напишите нам, посчитаем вручную.",
  },
  {
    q: "Как получить заказ?",
    a: "Самовывоз из мастерской в Москве или курьер — выбирается при оформлении, стоимость доставки видна в итоге до оплаты. Статус заказа — по ссылке: принят → оплачен → печатается → готов.",
  },
  {
    q: "Работаете с юрлицами?",
    a: "Да. При оформлении укажите ИНН — счёт появится сразу, оплата по счёту без карты. На тираж от 10 и от 50 штук скидка считается автоматически.",
  },
];

/** Разметка FAQPage для поиска (schema.org) — Яндекс и Google показывают такие ответы в выдаче. */
export function faqJsonLd(faq: { q: string; a: string }[] = FAQ): object {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faq.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };
}

/** Адрес API для серверного рендера (внутри docker — http://api:8000). */
export function apiInternalUrl(): string {
  return process.env.API_INTERNAL_URL ?? "http://localhost:8000";
}

/**
 * Прайс для главной. Ходит в API с сервера Next; если API недоступен (сборка образа,
 * dev без uvicorn) — null, и страница рендерится без цен, а не падает.
 */
/** Справочник материалов для карточек (B44). Нет API — пустой список (карточки по прайсу). */
export async function loadMaterials(): Promise<MaterialItem[]> {
  try {
    const r = await fetch(`${apiInternalUrl()}/api/v1/materials`, { next: { revalidate: 600 } });
    if (!r.ok) return [];
    return ((await r.json()) as MaterialsResponse).items ?? [];
  } catch {
    return [];
  }
}

export async function loadPricing(): Promise<Pricing | null> {
  try {
    const r = await fetch(`${apiInternalUrl()}/api/v1/pricing`, { next: { revalidate: 600 } });
    if (!r.ok) return null;
    return (await r.json()) as Pricing;
  } catch {
    return null;
  }
}
