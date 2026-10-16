/** Форматирует цену в рублях: 2500 → «2 500 ₽». */
export function formatPrice(rub: number): string {
  const rounded = Math.round(rub);
  const withSpaces = rounded.toLocaleString("ru-RU").replace(/ /g, " ");
  return `${withSpaces} ₽`;
}
