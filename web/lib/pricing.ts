/** Цена (B05): типы ответов API /pricing и /quote, подписи вариантов, строки разложения суммы. */

import { formatPrice, formatPriceExact } from "./format";

/** GET /api/v1/pricing — прайс для формы. Числа — ₽. */
export type Pricing = {
  currency: string;
  min_order: number;
  margin: number;
  k_supports: number;
  materials: Record<string, { price_per_g: number; tech: string }>;
  technologies: Record<string, { machine_rate: number }>;
  batch: { from: number; k: number }[];
  postprocess: Record<string, number>;
  delivery: Record<string, number>;
};

/** POST /api/v1/uploads/{id}/quote — расчёт цены. */
export type Quote = {
  id: string;
  upload_id: string;
  original_name?: string | null;
  created_at: string;
  expires_at?: string | null; // до какого момента расчёт принимает заказ (null — без срока)
  currency: string;
  material: string;
  tech: string;
  supports: boolean;
  qty: number;
  postprocess: string;
  delivery: string;
  material_g: number;
  print_time_s: number;
  price_per_g: number;
  machine_rate: number;
  k_supports: number;
  k_batch: number;
  margin: number;
  min_order: number;
  material_cost: number;
  machine_cost: number;
  unit_price: number;
  print_subtotal: number;
  min_order_applied: boolean;
  postprocess_cost: number;
  delivery_cost: number;
  total: number;
};

export const POSTPROCESS_LABELS: Record<string, string> = {
  none: "Без обработки",
  sanding: "Шлифовка",
  painting: "Грунт и покраска в один цвет",
};

export const DELIVERY_LABELS: Record<string, string> = {
  pickup: "Самовывоз (Москва)",
  courier_moscow: "Курьер по Москве",
  cdek: "СДЭК до пункта выдачи (Россия)",
};

/**
 * Цена грамма для клиента — материал с наценкой: price_per_g × (1 + margin), до 0,1 ₽.
 * Без часа принтера, поэтому на сайте пишем «от …» (B45: раньше показывали число без наценки).
 */
export function clientPerGram(pricing: Pricing, material: string): number | null {
  const m = pricing.materials[material];
  if (!m) return null;
  return Math.round(m.price_per_g * (1 + pricing.margin) * 10) / 10;
}

/** 5.4 → «5,4 ₽», 12 → «12 ₽» — цена за грамм без лишних нулей. */
export function formatPerGram(rub: number): string {
  const rounded = Math.round(rub * 100) / 100;
  return `${String(rounded).replace(".", ",")} ₽`;
}

/** Подпись варианта с ценой: «Шлифовка (+150 ₽/шт)», «Самовывоз (Москва)» при 0 ₽. */
export function optionLabel(labels: Record<string, string>, key: string, price: number, perItem: boolean): string {
  const name = labels[key] ?? key;
  if (price <= 0) return name;
  return `${name} (+${formatPrice(price)}${perItem ? "/шт" : ""})`;
}

/** Подсказка про скидку за тираж: «от 10 шт — −10 %, от 50 шт — −20 %». Пусто, если скидок нет. */
export function batchHint(batch: Pricing["batch"]): string {
  const parts = batch
    .filter((t) => t.k < 1)
    .map((t) => `от ${t.from} шт — −${Math.round((1 - t.k) * 100)} %`);
  return parts.join(", ");
}

/** Строки «за что платим» для таблицы под итогом. */
export function quoteLines(q: Quote): { label: string; value: string }[] {
  const lines: { label: string; value: string }[] = [];
  const perItem = q.qty > 1 ? ` × ${q.qty} шт` : "";
  const r2 = (v: number) => Math.round(v * 100) / 100;
  if (q.qty === 1) {
    lines.push({ label: "Печать одного изделия", value: formatPrice(q.unit_price) });
  } else if (q.k_batch >= 1) {
    // Тираж без скидки: цена за штуку × тираж = сумма (с копейками, чтобы сходилось).
    lines.push({ label: "Цена за штуку", value: formatPriceExact(q.unit_price) });
    lines.push({ label: `Печать${perItem}`, value: formatPriceExact(q.print_subtotal) });
  } else {
    // Тираж со скидкой (UX 05.11, персона 3): unit_price из API уже со скидкой,
    // поэтому показываем цену за штуку ДО скидки, сумму до скидки, скидку в рублях
    // и итог. Скидка = «до» − «после», так строки сходятся копейка в копейку.
    const percent = Math.round((1 - q.k_batch) * 100);
    const fullUnit = r2(q.unit_price / q.k_batch);
    const fullSubtotal = r2(fullUnit * q.qty);
    const discount = r2(fullSubtotal - q.print_subtotal);
    lines.push({ label: "Цена за штуку без скидки", value: formatPriceExact(fullUnit) });
    lines.push({ label: `Печать${perItem}`, value: formatPriceExact(fullSubtotal) });
    lines.push({ label: `Скидка за тираж −${percent} %`, value: `−${formatPriceExact(discount)}` });
    lines.push({
      label: `Печать со скидкой (${formatPriceExact(q.unit_price)} за шт)`,
      value: formatPriceExact(q.print_subtotal),
    });
  }
  if (q.supports) {
    lines.push({ label: "Поддержки", value: `×${q.k_supports.toString().replace(".", ",")}` });
  }
  if (q.min_order_applied) {
    lines.push({ label: "Минимальный заказ", value: formatPrice(q.min_order) });
  }
  if (q.postprocess_cost > 0) {
    lines.push({
      label: `${POSTPROCESS_LABELS[q.postprocess] ?? q.postprocess}${perItem}`,
      value: formatPrice(q.postprocess_cost),
    });
  }
  lines.push({
    label: DELIVERY_LABELS[q.delivery] ?? q.delivery,
    value: q.delivery_cost > 0 ? formatPrice(q.delivery_cost) : "бесплатно",
  });
  return lines;
}
