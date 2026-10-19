/** Заказ (B06): типы ответа API /orders, статусы, проверка формы на клиенте. */

import type { PaymentInfo } from "./payment";
import type { Quote } from "./pricing";

export type OrderStatus = "new" | "paid" | "printing" | "ready" | "done" | "cancelled";

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
};

export const EMPTY_FORM: OrderForm = {
  name: "",
  phone: "",
  email: "",
  address: "",
  comment: "",
  consent: false,
};

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
