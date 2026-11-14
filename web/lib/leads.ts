/**
 * Быстрые заявки (B52) — для тех, кто не дошёл до заказа.
 *
 * 1. Выходной попап «Оставьте телефон — посчитаем вручную» (components/ExitPopup.tsx).
 *    Показывается один раз: на компьютере — когда курсор уходит за верх окна (к вкладкам / крестику),
 *    на телефоне — когда клиент ушёл в другое приложение/вкладку и вернулся (сравнивает цены).
 *    Только на страницах выбора модели (загрузка, каталог, редакторы) и не раньше, чем через
 *    MIN_ENGAGED_MS на сайте. Закрыл — не показываем DISMISS_DAYS дней, оставил телефон — SENT_DAYS.
 *    POST /api/v1/leads/callback.
 * 2. Страница /request «Нет файла? Пришлите фото или описание» (components/BriefForm.tsx).
 *    POST /api/v1/leads/brief (form-data, фото по желанию).
 *
 * Заявки ложатся в таблицу leads → /admin/leads, Telegram и/или письмо владельцу (api/app/leads.py).
 * Что сказать клиенту после отправки — leadSentMessage из lib/materials.ts (честно, если каналов нет).
 */

import { isValidEmail, isValidPhone } from "./order";

// --- выходной попап -------------------------------------------------------------------------

export const EXIT_STORAGE_KEY = "tuc:exit-popup";
export const MIN_ENGAGED_MS = 20_000; // раньше 20 с не мешаем — человек ещё осматривается
export const AWAY_MIN_MS = 5_000; // на телефоне: был в другой вкладке/приложении дольше 5 с
export const DISMISS_DAYS = 7;
export const SENT_DAYS = 30;
const DAY_MS = 24 * 60 * 60 * 1000;

/** Страницы, где клиент выбирает модель и ещё не оформил заказ. */
export function exitPopupPage(path: string): boolean {
  return /^\/(upload|catalog|editors)(\/|$)/.test(path);
}

/** Что запомнили в localStorage: когда закрыли или отправили. */
export type ExitMemory = { until: number } | null;

export function parseExitMemory(raw: string | null): ExitMemory {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as { until?: unknown };
    return typeof v.until === "number" ? { until: v.until } : null;
  } catch {
    return null;
  }
}

/** Запись в localStorage после закрытия (sent=false) или отправки телефона (sent=true). */
export function exitMemory(now: number, sent: boolean): string {
  const days = sent ? SENT_DAYS : DISMISS_DAYS;
  return JSON.stringify({ until: now + days * DAY_MS });
}

/** Можно ли сейчас показать попап (страница, пауза после закрытия, время на сайте). */
export function exitPopupAllowed(opts: {
  path: string;
  memory: ExitMemory;
  shownThisSession: boolean;
  engagedMs: number;
  now: number;
}): boolean {
  if (!exitPopupPage(opts.path)) return false;
  if (opts.shownThisSession) return false;
  if (opts.memory && opts.memory.until > opts.now) return false;
  return opts.engagedMs >= MIN_ENGAGED_MS;
}

/** Компьютер: курсор ушёл за верхний край окна (к вкладкам, адресной строке, крестику). */
export function isDesktopExit(e: { clientY: number; relatedTarget: unknown }): boolean {
  return e.relatedTarget == null && e.clientY <= 0;
}

/** Телефон: вкладка снова видна, а клиента не было дольше AWAY_MIN_MS. */
export function isPhoneReturn(hiddenAt: number | null, now: number): boolean {
  return hiddenAt != null && now - hiddenAt >= AWAY_MIN_MS;
}

/** id загрузки из адреса /upload/<id>[/…] — чтобы владелец видел, какую модель смотрел клиент. */
export function uploadIdFromPath(path: string): string | null {
  const m = /^\/upload\/([0-9a-f]{32})(\/|$)/.exec(path);
  return m ? m[1] : null;
}

export type CallbackForm = { name: string; phone: string };

export function validateCallback(form: CallbackForm): Partial<Record<keyof CallbackForm, string>> {
  const errors: Partial<Record<keyof CallbackForm, string>> = {};
  if (!isValidPhone(form.phone)) errors.phone = "Телефон в формате +7 999 123-45-67.";
  return errors;
}

/** Тело POST /api/v1/leads/callback. */
export function callbackRequest(form: CallbackForm, path: string) {
  return {
    phone: form.phone.trim(),
    name: form.name.trim() || null,
    page: path,
    upload_id: uploadIdFromPath(path),
  };
}

// --- заявка без модели ----------------------------------------------------------------------

export const PHOTO_MAX_MB = 10;
export const PHOTO_ACCEPT = "image/jpeg,image/png,image/webp,image/heic,.heic";

export type BriefForm = {
  name: string;
  phone: string;
  email: string;
  comment: string;
  qty: string;
};

export const EMPTY_BRIEF: BriefForm = { name: "", phone: "", email: "", comment: "", qty: "1" };

export function validateBrief(
  form: BriefForm,
  photo: { size: number; name: string } | null,
): Partial<Record<keyof BriefForm | "photo", string>> {
  const errors: Partial<Record<keyof BriefForm | "photo", string>> = {};
  if (!form.name.trim()) errors.name = "Как к вам обращаться?";
  if (!isValidPhone(form.phone)) errors.phone = "Телефон в формате +7 999 123-45-67.";
  if (form.email.trim() && !isValidEmail(form.email)) errors.email = "Проверьте e-mail.";
  if (form.comment.trim().length < 5)
    errors.comment = "Опишите, что нужно: что за деталь, размеры, для чего.";
  const qty = Number(form.qty);
  if (!Number.isInteger(qty) || qty < 1 || qty > 10000) errors.qty = "От 1 до 10 000 шт.";
  if (photo) {
    if (photo.size > PHOTO_MAX_MB * 1024 * 1024) errors.photo = `Фото больше ${PHOTO_MAX_MB} МБ.`;
    else if (!/\.(jpe?g|png|webp|heic)$/i.test(photo.name))
      errors.photo = "Фото — в формате JPG, PNG, WEBP или HEIC.";
  }
  return errors;
}

/** Тело POST /api/v1/leads/brief (form-data — из-за фото). */
export function briefFormData(form: BriefForm, photo: Blob | null, path: string): FormData {
  const fd = new FormData();
  fd.set("name", form.name.trim());
  fd.set("phone", form.phone.trim());
  fd.set("comment", form.comment.trim());
  if (form.email.trim()) fd.set("email", form.email.trim());
  fd.set("qty", String(Number(form.qty) || 1));
  fd.set("page", path);
  if (photo) fd.set("photo", photo, (photo as File).name || "photo.jpg");
  return fd;
}
