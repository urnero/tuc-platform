/**
 * Справочник материалов (B44): ответ GET /api/v1/materials. Источник — config/materials.yaml,
 * владелец правит yaml — сайт подхватывает сам (главная — раз в 10 минут, форма — сразу).
 *
 * FDM-материалы (`materials`) считает слайсер, цена — сразу на сайте.
 * Смолы (`on_request`) — «цена по запросу»: клиент оставляет заявку без оплаты
 * (POST /api/v1/uploads/{id}/request), владелец называет цену сам.
 */

import { isValidEmail, isValidPhone } from "./order";

export type MaterialItem = {
  key: string;
  tech: "FDM" | "SLA";
  name: string;
  tagline: string;
  hint: string;
  pros: string[];
  cons: string[];
  uses: string[];
  colors: string[];
  heat_c: number | null;
  needs_enclosure: boolean;
  max_mm: [number, number, number] | null;
  enabled: boolean;
  on_request: boolean;
};

export type MaterialsResponse = {
  /** ключи, которые считает слайсер (по порядку для выбора) */
  materials: string[];
  /** смолы — цена по запросу */
  on_request?: string[];
  /** справочник для карточек и подсказок */
  items?: MaterialItem[];
};

/** Без API (или старый API без справочника): три базовых материала. */
export const FALLBACK_MATERIALS: MaterialsResponse = {
  materials: ["PLA", "PETG", "ABS"],
  on_request: [],
  items: [],
};

/** 256×256×256 → «256 × 256 × 256 мм». */
export function formatSize(mm: [number, number, number]): string {
  return `${mm.map((v) => String(v).replace(".", ",")).join(" × ")} мм`;
}

/** Короткие факты для карточки: «до 110 °C», «закрытая камера», «до 256 × 256 × 256 мм». */
export function materialFacts(item: MaterialItem): string[] {
  const facts: string[] = [];
  if (item.heat_c) facts.push(`держит до ${item.heat_c} °C`);
  if (item.needs_enclosure) facts.push("печать в закрытой камере");
  if (item.max_mm) facts.push(`деталь до ${formatSize(item.max_mm)}`);
  if (item.colors.length) facts.push(`цвета: ${item.colors.join(", ")}`);
  return facts;
}

/** Подсказка под выбором материала: из справочника, иначе — запасной текст. */
export function materialHint(
  key: string,
  items: MaterialItem[] | undefined,
  fallback: Record<string, string>,
): string {
  const item = items?.find((i) => i.key === key);
  return item?.hint || fallback[key] || "";
}

/** Подпись варианта в выпадающем списке. */
export function materialOptionLabel(
  key: string,
  items: MaterialItem[] | undefined,
): string {
  const item = items?.find((i) => i.key === key);
  if (!item) return key;
  return item.tagline ? `${item.name} — ${item.tagline}` : item.name;
}

export type LeadForm = {
  name: string;
  phone: string;
  email: string;
  comment: string;
};

export const EMPTY_LEAD: LeadForm = {
  name: "",
  phone: "",
  email: "",
  comment: "",
};

/** Ошибки заявки «цена по запросу» по полям; пустой объект — можно отправлять. */
export function validateLead(
  form: LeadForm,
): Partial<Record<keyof LeadForm, string>> {
  const errors: Partial<Record<keyof LeadForm, string>> = {};
  if (!form.name.trim()) errors.name = "Как к вам обращаться?";
  if (!isValidPhone(form.phone))
    errors.phone = "Телефон в формате +7 999 123-45-67.";
  if (form.email.trim() && !isValidEmail(form.email))
    errors.email = "Проверьте e-mail.";
  return errors;
}

/** Тело POST /api/v1/uploads/{id}/request. */
export function leadRequest(form: LeadForm, material: string, qty: number) {
  return {
    material,
    qty,
    name: form.name.trim(),
    phone: form.phone.trim(),
    email: form.email.trim() || null,
    comment: form.comment.trim() || null,
  };
}
