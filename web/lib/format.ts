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
