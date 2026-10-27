/**
 * Реквизиты и контакты студии (B13). ЕДИНСТВЕННОЕ место, где они записаны:
 * отсюда их берут оферта (/offer), политика ПДн (/policy), «О студии» (/about),
 * «Контакты» (/contacts) и подвал сайта.
 *
 * Владелец заполняет пустые строки и пересобирает web (`docker compose up -d --build web`
 * или просто пуш в dev/main — деплой пересоберёт сам). Пока поле пустое, на страницах
 * вместо него показывается пометка «уточняется», а на странице контактов — предупреждение.
 */

export const COMPANY = {
  /** Торговое название студии. */
  brand: "BroPrint",
  city: "Москва",

  // --- Юридические реквизиты (нужны в оферте и политике ПДн) ---
  /** Кто исполнитель по оферте: «ИП Иванов Иван Иванович» или
   *  «Иванов Иван Иванович, плательщик налога на профессиональный доход (самозанятый)». */
  legalName: "",
  inn: "",
  /** ОГРНИП — только для ИП; самозанятый оставляет пустым. */
  ogrnip: "",
  /** Адрес для писем и претензий (почтовый, с индексом). */
  legalAddress: "",

  // --- Банковские реквизиты — для счёта юрлицам (B33, /order/<token>/invoice) ---
  /** Название банка, например «АО „Т-Банк“». */
  bankName: "",
  /** БИК банка — 9 цифр. */
  bik: "",
  /** Расчётный счёт — 20 цифр. */
  bankAccount: "",
  /** Корреспондентский счёт банка — 20 цифр. */
  corrAccount: "",

  // --- Контакты для клиентов ---
  /** Почта для вопросов по заказам и для отзыва согласия на обработку ПДн. */
  email: "",
  /** В формате +7 999 123-45-67. */
  phone: "",
  /** Ник в Telegram без @, например «tuc_print». */
  telegram: "",
  /** Адрес самовывоза (улица, дом, как найти). */
  pickupAddress: "",
  /** Когда можно забрать заказ и когда отвечаем, например «пн–пт 11:00–20:00». */
  hours: "",

  /** Дата редакции оферты и политики, ГГГГ-ММ-ДД. Меняется при каждой правке текстов. */
  documentsDate: "2026-10-21",
};

export type CompanyField = keyof typeof COMPANY;

/** Поля, без которых оферта и политика ПДн не имеют юридической силы — их надо заполнить до продаж. */
export const REQUIRED_FIELDS: CompanyField[] = ["legalName", "inn", "legalAddress", "email"];

/** Русские названия полей — для предупреждения «не заполнено». */
export const FIELD_LABELS: Record<CompanyField, string> = {
  brand: "название",
  city: "город",
  legalName: "наименование исполнителя",
  inn: "ИНН",
  ogrnip: "ОГРНИП",
  legalAddress: "адрес",
  bankName: "банк",
  bik: "БИК",
  bankAccount: "расчётный счёт",
  corrAccount: "корреспондентский счёт",
  email: "e-mail",
  phone: "телефон",
  telegram: "Telegram",
  pickupAddress: "адрес самовывоза",
  hours: "часы работы",
  documentsDate: "дата документов",
};

/** Текст-заглушка, который видит клиент вместо пустого поля. */
export const PLACEHOLDER = "уточняется";

/** Наименование исполнителя стоит внутри фраз оферты — ему нужна заглушка, читаемая как подлежащее. */
export const LEGAL_NAME_PLACEHOLDER = "Исполнитель (наименование уточняется)";

/** Значение поля или заглушка, если владелец его ещё не заполнил. */
export function requisite(field: CompanyField, company: typeof COMPANY = COMPANY): string {
  const value = company[field].trim();
  if (value !== "") return value;
  return field === "legalName" ? LEGAL_NAME_PLACEHOLDER : PLACEHOLDER;
}

/** Без этих полей счёт юрлицу (B33) оплатить нельзя: банк не проведёт платёж. */
export const INVOICE_FIELDS: CompanyField[] = ["legalName", "inn", "legalAddress", "bankName", "bik", "bankAccount", "corrAccount"];

/** Обязательные поля, которые ещё пусты (для предупреждения владельцу на страницах). */
export function missingRequisites(company: typeof COMPANY = COMPANY): string[] {
  return REQUIRED_FIELDS.filter((f) => company[f].trim() === "").map((f) => FIELD_LABELS[f]);
}

/** Реквизиты для счёта, которые ещё пусты (по-русски) — пока они есть, счёт показывается с предупреждением. */
export function missingInvoiceRequisites(company: typeof COMPANY = COMPANY): string[] {
  return INVOICE_FIELDS.filter((f) => company[f].trim() === "").map((f) => FIELD_LABELS[f]);
}

/** «2026-10-21» → «21 октября 2026 г.» — так дата редакции пишется в документах. */
export function formatDocumentsDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  const date = new Date(Date.UTC(y, m - 1, d));
  return `${date.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })}`;
}

/** Ссылка на Telegram из ника; пустой ник → null. */
export function telegramUrl(nick: string): string | null {
  const clean = nick.trim().replace(/^@/, "");
  return clean === "" ? null : `https://t.me/${clean}`;
}

/** Телефон в ссылку tel: («+7 999 123-45-67» → «tel:+79991234567»); пусто → null. */
export function phoneUrl(phone: string): string | null {
  const digits = phone.replace(/[^\d+]/g, "");
  return digits === "" ? null : `tel:${digits}`;
}
