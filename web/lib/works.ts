/**
 * Примеры работ для главной (B14).
 *
 * Как добавить фото: положить JPG/PNG/WebP в `web/public/works/` (например `korpus.jpg`,
 * лучше 1200×900, до 300 КБ) и вписать имя файла в `image` ниже. Пока `image: null`,
 * карточка показывается с рисунком-заглушкой, а раздел называется «Что печатаем»;
 * как только появится хоть одно фото — «Примеры работ».
 * Тест lib/works.test.ts проверяет, что каждый указанный файл действительно лежит в public/works.
 */

export type Work = {
  /** Короткое название карточки. */
  title: string;
  /** Одна фраза: что это и зачем. */
  text: string;
  /** Материал из profiles/filament (PLA, PETG, ABS). */
  material: string;
  /** Имя файла в web/public/works/ или null, пока фото нет. */
  image: string | null;
};

export const WORKS: Work[] = [
  { title: "Корпус для электроники", text: "Коробка под плату с отверстиями под разъёмы и крышкой на защёлках.", material: "PETG", image: null },
  { title: "Деталь взамен сломанной", text: "Шестерня, защёлка, крепление — по вашей модели или по образцу.", material: "ABS", image: null },
  { title: "Кронштейн и крепёж", text: "Уголки, держатели, кронштейны под полку, камеру или датчик.", material: "PETG", image: null },
  { title: "Макет и прототип", text: "Проверить форму и посадку до заказа на производстве.", material: "PLA", image: null },
  { title: "Табличка с текстом", text: "Бирка, номер, именная табличка — с выпуклым или утопленным текстом.", material: "PLA", image: null },
  { title: "Мелкая серия", text: "10–100 одинаковых деталей со скидкой за тираж.", material: "PLA", image: null },
];

/** Путь к фото для <img src>: «korpus.jpg» → «/works/korpus.jpg»; без фото — null. */
export function workImageUrl(work: Work): string | null {
  const name = work.image?.trim();
  return name ? `/works/${name}` : null;
}

/** Заголовок раздела: пока фото нет — честное «Что печатаем». */
export function worksTitle(works: Work[]): string {
  return works.some((w) => workImageUrl(w) !== null) ? "Примеры работ" : "Что печатаем";
}
