/** Форматирует цену в рублях: 2500 → «2 500 ₽». */
export function formatPrice(rub: number): string {
  const rounded = Math.round(rub);
  const withSpaces = rounded.toLocaleString("ru-RU").replace(/ /g, " ");
  return `${withSpaces} ₽`;
}

/**
 * Цена с копейками, если они есть: 77.15 → «77,15 ₽», 3086 → «3 086 ₽».
 * Нужна в разбивке тиража: цена за штуку × тираж должна сходиться с суммой копейка в копейку.
 */
export function formatPriceExact(rub: number): string {
  const cents = Math.round(rub * 100);
  if (cents % 100 === 0) return formatPrice(cents / 100);
  const text = (cents / 100)
    .toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    .replace(/[\u00a0\u202f]/g, " ");
  return `${text} ₽`;
}

/**
 * Короткий номер расчёта для клиента: из технического id
 * «7f763449bbc546f1b1a443918469791a-026903» (id загрузки + метка параметров)
 * делаем «7F76-6903» — 4 знака модели и 4 знака параметров, 8 символов.
 * Полный id остаётся в ссылке на заказ и в подсказке (title) — по нему ищет поддержка.
 */
export function shortQuoteNo(quoteId: string): string {
  const [upload, params] = quoteId.split("-");
  if (!upload || !params) return quoteId.slice(0, 8).toUpperCase();
  return `${upload.slice(0, 4)}-${params.slice(-4)}`.toUpperCase();
}
