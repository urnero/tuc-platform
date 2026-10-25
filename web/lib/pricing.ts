/** Цена (B05): типы ответов API /pricing и /quote, подписи вариантов, строки разложения суммы. */

import { formatPrice } from "./format";

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
};

export const DELIVERY_LABELS: Record<string, string> = {
  pickup: "Самовывоз (Москва)",
  courier_moscow: "Курьер по Москве",
};

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
  lines.push({ label: "Печать одного изделия", value: formatPrice(q.unit_price) });
  if (q.qty > 1) {
    lines.push({ label: `Печать${perItem}`, value: formatPrice(q.print_subtotal) });
  }
  if (q.k_batch < 1) {
    lines.push({ label: "Скидка за тираж", value: `−${Math.round((1 - q.k_batch) * 100)} %` });
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
