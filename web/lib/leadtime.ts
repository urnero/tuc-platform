/**
 * Срок изготовления в расчёте (UX, персона 2): «Готово через 1–3 рабочих дня».
 *
 * Считаем грубо, по часам печати из расчёта — это ориентир, не обещание до часа.
 * Владелец правит константы ниже, если реальный срок другой. Правило записано в docs/DECISIONS.md.
 *
 *   часы = время печати одной штуки × тираж
 *   принтеров = min(тираж, PARALLEL_PRINTERS)  — тираж раскладываем на несколько принтеров
 *   дней печати = ceil(часы / (HOURS_PER_DAY × принтеров)), минимум 1
 *   срок = от «дней печати» до «дней печати + QUEUE_DAYS» + дни обработки
 *
 * Небольшая деталь (до ~20 ч печати) даёт «1–3 рабочих дня» — как обещано на главной (STUDIO.leadTime).
 */

import { plural } from "./invoice";

/** Сколько часов в сутки реально печатает один принтер (с перезапусками и снятием деталей). */
export const HOURS_PER_DAY = 20;
/** На сколько принтеров одновременно раскладываем тираж (тиражных FDM в парке 5, берём с запасом). */
export const PARALLEL_PRINTERS = 3;
/** Запас на очередь и проверку файла: верхняя граница срока = дни печати + QUEUE_DAYS. */
export const QUEUE_DAYS = 2;
/** Сколько рабочих дней добавляет постобработка (ключи — как в config/pricing.yaml postprocess). */
export const POSTPROCESS_DAYS: Record<string, number> = { none: 0, sanding: 1, painting: 2 };

/** Срок в рабочих днях «от–до». Пустые/неверные числа → null (строку не показываем). */
export function leadTimeDays(
  printTimeS: number,
  qty: number,
  postprocess = "none",
): { min: number; max: number } | null {
  if (!Number.isFinite(printTimeS) || printTimeS <= 0 || !Number.isFinite(qty) || qty < 1) return null;
  const hours = (printTimeS * Math.floor(qty)) / 3600;
  const printers = Math.min(Math.floor(qty), PARALLEL_PRINTERS);
  const printDays = Math.max(1, Math.ceil(hours / (HOURS_PER_DAY * printers)));
  const extra = POSTPROCESS_DAYS[postprocess] ?? 0;
  return { min: printDays + extra, max: printDays + QUEUE_DAYS + extra };
}

/** «Готово через 1–3 рабочих дня» / «Готово через 4–6 рабочих дней». null — если срок не посчитать. */
export function leadTimeText(printTimeS: number, qty: number, postprocess = "none"): string | null {
  const d = leadTimeDays(printTimeS, qty, postprocess);
  if (!d) return null;
  // «рабочих дня/дней» согласуется с верхним числом: «1–3 рабочих дня», «4–6 рабочих дней».
  const word = plural(d.max, ["рабочий день", "рабочих дня", "рабочих дней"]);
  return `Готово через ${d.min}–${d.max} ${word}`;
}
