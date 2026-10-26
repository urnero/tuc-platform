/** Заказ (B06): типы ответа API /orders, статусы, проверка формы на клиенте.
 *  B33: заказ от организации или ИП — блок `company`, оплата по счёту (`payment_method = invoice`). */

import type { PaymentInfo } from "./payment";
import type { Quote } from "./pricing";

export type OrderStatus = "new" | "paid" | "printing" | "ready" | "done" | "cancelled";

/** online — картой через ЮKassa; invoice — по счёту безналом (организации и ИП, B33). */
export type PaymentMethod = "online" | "invoice";

/** Покупатель-юрлицо в заказе (B33). КПП есть только у организаций, у ИП — null. */
export type Company = {
  name: string;
  inn: string;
  kpp: string | null;
  address: string | null;
};

/** GET /api/v1/orders/{token} и ответ POST /api/v1/orders. */
export type Order = {
  id: number;
  number: string; // «ТУЦ-12»
  token: string;
  status: OrderStatus;
  created_at: string;
  updated_at: string;
  customer_name: string;
  phone: string;
  email: string | null;
  delivery: string;
  address: string | null;
  comment: string | null;
  company?: Company | null; // B33: null — заказ от частного лица
  payment_method?: PaymentMethod; // B33: у старых ответов API поля нет → online
  upload_id: string;
  quote_id: string;
  original_name: string | null;
  material: string;
  supports: boolean;
  qty: number;
  postprocess: string;
  total: number;
  currency: string;
  quote: Quote;
  payment?: PaymentInfo; // оплата (B08): есть в ответах API начиная с B08
};

/** Что видит клиент на странице статуса. */
export const STATUS_LABELS: Record<OrderStatus, string> = {
  new: "Принят",
  paid: "Оплачен",
  printing: "Печатается",
  ready: "Готов",
  done: "Выдан",
  cancelled: "Отменён",
};

export const STATUS_HINTS: Record<OrderStatus, string> = {
  new: "Мы получили заказ. Менеджер проверит модель и свяжется с вами, чтобы подтвердить цену и срок.",
  paid: "Оплата получена. Скоро поставим модель в печать.",
  printing: "Модель на принтере. Когда будет готова — напишем.",
  ready: "Заказ готов: можно забирать или ждать курьера.",
  done: "Заказ выдан. Спасибо, что печатаете с нами!",
  cancelled: "Заказ отменён. Если это ошибка — напишите нам.",
};

/** Порядок шагов для полоски прогресса; отменённый — вне полоски. */
export const STATUS_STEPS: OrderStatus[] = ["new", "paid", "printing", "ready", "done"];

/** Форма заказа: что заполняет клиент. Доставка берётся из расчёта цены. */
export type OrderForm = {
  name: string;
  phone: string;
  email: string;
  address: string;
  comment: string;
  consent: boolean;
  // B33: заказ от организации или ИП → оплата по счёту
  b2b: boolean;
  companyName: string;
  inn: string;
  kpp: string;
  companyAddress: string;
};

export const EMPTY_FORM: OrderForm = {
  name: "",
  phone: "",
  email: "",
  address: "",
  comment: "",
  consent: false,
  b2b: false,
  companyName: "",
  inn: "",
  kpp: "",
  companyAddress: "",
};

/** Заказ оплачивается по счёту (B33)? У ответов API до B33 поля нет — считаем «онлайн». */
export function paysByInvoice(order: Pick<Order, "payment_method">): boolean {
  return order.payment_method === "invoice";
}

// Контрольные суммы ИНН (ФНС) — та же проверка, что на сервере (api/app/b2b.py).
const W10 = [2, 4, 10, 3, 5, 9, 4, 6, 8];
const W11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8];
const W12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8];

function checkDigit(digits: string, weights: number[]): number {
  let sum = 0;
  for (let i = 0; i < weights.length; i++) sum += Number(digits[i]) * weights[i];
  return (sum % 11) % 10;
}

/** «7707083893» → "org" (организация), «500100732259» → "ip" (ИП), иначе null — не ИНН. */
export function innKind(raw: string): "org" | "ip" | null {
  const inn = raw.replace(/\s/g, "");
  if (!/^\d+$/.test(inn)) return null;
  if (inn.length === 10) return checkDigit(inn, W10) === Number(inn[9]) ? "org" : null;
  if (inn.length === 12) {
    const ok = checkDigit(inn, W11) === Number(inn[10]) && checkDigit(inn, W12) === Number(inn[11]);
    return ok ? "ip" : null;
  }
  return null;
}

/** КПП — 9 знаков: 4 цифры, 2 цифры или заглавные латинские буквы, 3 цифры. */
export function isValidKpp(raw: string): boolean {
  return /^\d{4}[\dA-Z]{2}\d{3}$/.test(raw.trim());
}

/** Подставить в пустые поля формы контакты клиента из кабинета (B32): что он уже ввёл — не трогаем. */
export function prefillForm(
  form: OrderForm,
  account: { email: string; contacts: { name: string; phone: string; address: string } | null },
): OrderForm {
  const c = account.contacts;
  return {
    ...form,
    name: form.name || c?.name || "",
    phone: form.phone || c?.phone || "",
    email: form.email || account.email,
    address: form.address || c?.address || "",
  };
}

export function needsAddress(delivery: string): boolean {
  return delivery !== "pickup";
}

/** Та же проверка телефона, что на сервере: российские 10–11 цифр или иностранный с «+». */
export function isValidPhone(raw: string): boolean {
  const digits = raw.replace(/\D/g, "");
  if (digits.length === 11 && (digits[0] === "7" || digits[0] === "8")) return true;
  if (digits.length === 10 && digits[0] === "9") return true;
  return raw.trim().startsWith("+") && digits.length >= 10 && digits.length <= 15;
}

export function isValidEmail(raw: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw.trim());
}

/** Ошибки формы по полям; пустой объект — можно отправлять. */
export function validateForm(form: OrderForm, delivery: string): Partial<Record<keyof OrderForm, string>> {
  const errors: Partial<Record<keyof OrderForm, string>> = {};
  if (!form.name.trim()) errors.name = "Как к вам обращаться?";
  if (!isValidPhone(form.phone)) errors.phone = "Телефон в формате +7 999 123-45-67.";
  if (form.email.trim() && !isValidEmail(form.email)) errors.email = "Проверьте e-mail.";
  if (needsAddress(delivery) && !form.address.trim()) errors.address = "Куда доставить?";
  if (form.b2b) {
    // Организации (B33): счёт уходит на e-mail, ИНН проверяем по контрольным цифрам.
    if (!form.email.trim()) errors.email = "Для счёта нужен e-mail.";
    if (!form.companyName.trim()) errors.companyName = "Укажите наименование организации или ИП.";
    if (!innKind(form.inn)) errors.inn = "ИНН: 10 цифр у организации, 12 — у ИП.";
    if (innKind(form.inn) === "org" && form.kpp.trim() && !isValidKpp(form.kpp)) {
      errors.kpp = "КПП — 9 знаков, например 770101001.";
    }
  }
  if (!form.consent) errors.consent = "Без согласия мы не можем принять заказ.";
  return errors;
}

/** Тело POST /api/v1/orders из формы. */
export function toRequest(form: OrderForm, quoteId: string) {
  return {
    quote_id: quoteId,
    name: form.name.trim(),
    phone: form.phone.trim(),
    email: form.email.trim() || null,
    address: form.address.trim() || null,
    comment: form.comment.trim() || null,
    consent: form.consent,
    company: form.b2b
      ? {
          name: form.companyName.trim(),
          inn: form.inn.replace(/\s/g, ""),
          // У ИП КПП нет — не отправляем, даже если поле заполнили.
          kpp: innKind(form.inn) === "org" ? form.kpp.trim() || null : null,
          address: form.companyAddress.trim() || null,
        }
      : null,
  };
}

/** «+79991234567» → «+7 999 123-45-67»; иностранный номер — как есть. */
export function formatPhone(phone: string): string {
  const m = /^\+7(\d{3})(\d{3})(\d{2})(\d{2})$/.exec(phone);
  return m ? `+7 ${m[1]} ${m[2]}-${m[3]}-${m[4]}` : phone;
}

/** «2026-10-19T20:40:00+00:00» → «19.10.2026, 23:40» по Москве. */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Из id расчёта (`<upload_id>-<хвост>`) — id загрузки, чтобы вернуть клиента на страницу модели. */
export function uploadIdFromQuote(quoteId: string): string | null {
  const m = /^([0-9a-f]{32})-[0-9a-f]{6}$/.exec(quoteId);
  return m ? m[1] : null;
}

/** Текст ошибки для страницы заказа, если расчёт не загрузился (GET /api/v1/quotes/{id}). */
export function quoteLoadError(status: number): string {
  if (status === 404) return "Расчёт не найден. Рассчитайте цену заново.";
  if (status === 410) return "Расчёт устарел — он действует 24 часа, цены могли измениться. Рассчитайте цену заново.";
  return `Ошибка ${status}.`;
}
