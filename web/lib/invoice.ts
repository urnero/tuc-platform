/**
 * Счёт на оплату для юрлица (B33): страница /order/<token>/invoice.
 *
 * Счёт — не строгий бланк, а привычная форма: шапка с банковскими реквизитами получателя,
 * «Счёт на оплату № BP-12 от 27 октября 2026 г.», поставщик, покупатель, таблица позиций,
 * итог, сумма прописью, подпись. Реквизиты студии — из `lib/company.ts`, покупатель и суммы —
 * из заказа (`orders.company*`, снимок расчёта `order.quote`). Клиент печатает страницу
 * или сохраняет в PDF кнопкой браузера и платит безналом; «оплачен» ставит владелец.
 *
 * НДС: студия — ИП или самозанятый без НДС, поэтому в счёте «Без НДС».
 */

import { COMPANY, missingInvoiceRequisites, requisite } from "./company";
import type { Order } from "./order";
import { DELIVERY_LABELS, POSTPROCESS_LABELS } from "./pricing";

export type InvoiceLine = { title: string; qty: number; unit: string; price: number; sum: number };

/** Позиции счёта из снимка расчёта: печать (за штуку), постобработка (за штуку), доставка (за заказ).
 *  Суммы — ровно те, что в заказе; минимальный заказ, если сработал, — одной строкой за 1 усл. */
export function invoiceLines(order: Order): InvoiceLine[] {
  const q = order.quote;
  const model = order.original_name ?? order.upload_id;
  const lines: InvoiceLine[] = [];
  const printTitle = `3D-печать (${order.material}${order.supports ? ", с поддержками" : ""}): ${model}`;
  if (q.min_order_applied) {
    lines.push({ title: `${printTitle}, ${order.qty} шт — минимальный заказ`, qty: 1, unit: "усл.", price: q.min_order, sum: q.min_order });
  } else {
    lines.push({ title: printTitle, qty: order.qty, unit: "шт", price: q.unit_price, sum: q.print_subtotal });
  }
  if (q.postprocess_cost > 0) {
    const label = POSTPROCESS_LABELS[order.postprocess] ?? order.postprocess;
    lines.push({ title: `Постобработка: ${label.toLowerCase()}`, qty: order.qty, unit: "шт", price: q.postprocess_cost / order.qty, sum: q.postprocess_cost });
  }
  if (q.delivery_cost > 0) {
    lines.push({ title: DELIVERY_LABELS[order.delivery] ?? order.delivery, qty: 1, unit: "усл.", price: q.delivery_cost, sum: q.delivery_cost });
  }
  // Итог заказа округлён до рубля (pricing.py), а позиции — с копейками: разницу в копейках
  // относим на строку печати, чтобы таблица сходилась ровно с суммой заказа.
  const diff = Math.round((order.total - lines.reduce((acc, l) => acc + l.sum, 0)) * 100) / 100;
  if (diff !== 0) {
    lines[0].sum = Math.round((lines[0].sum + diff) * 100) / 100;
    lines[0].price = Math.round((lines[0].sum / lines[0].qty) * 100) / 100;
  }
  return lines;
}

/** Номер счёта = номер заказа: «BP-12». */
export function invoiceNumber(order: Pick<Order, "number">): string {
  return order.number;
}

/** «2026-10-27T00:10:00+00:00» → «27 октября 2026 г.» по Москве. */
export function invoiceDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // toLocaleDateString в Node уже ставит «г.», в некоторых браузерах — нет: приводим к одному виду.
  const text = d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Moscow" });
  return text.endsWith("г.") ? text : `${text} г.`;
}

/** Назначение платежа для платёжки покупателя. */
export function paymentPurpose(order: Pick<Order, "number" | "created_at">): string {
  return `Оплата по счёту № ${order.number} от ${invoiceDate(order.created_at)} за услуги 3D-печати. Без НДС.`;
}

/** Реквизиты получателя для шапки счёта (пустые — «уточняется», плюс список недостающих). */
export function sellerRequisites(company: typeof COMPANY = COMPANY) {
  return {
    name: requisite("legalName", company),
    inn: requisite("inn", company),
    ogrnip: company.ogrnip.trim(),
    address: requisite("legalAddress", company),
    bankName: requisite("bankName", company),
    bik: requisite("bik", company),
    account: requisite("bankAccount", company),
    corrAccount: requisite("corrAccount", company),
    email: company.email.trim(),
    phone: company.phone.trim(),
    missing: missingInvoiceRequisites(company),
  };
}

// --- сумма прописью ------------------------------------------------------------------

const UNITS_M = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"];
const UNITS_F = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"];
const TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"];
const TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"];
const HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"];

/** Форма слова по числу: plural(1, ["рубль", "рубля", "рублей"]) → «рубль», 2 → «рубля», 5 → «рублей». */
export function plural(n: number, forms: [string, string, string]): string {
  const n10 = n % 10;
  const n100 = n % 100;
  if (n10 === 1 && n100 !== 11) return forms[0];
  if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return forms[1];
  return forms[2];
}

/** 0–999 словами; feminine — для тысяч («одна тысяча», «две тысячи»). Пусто для 0. */
function tripleWords(n: number, feminine: boolean): string {
  const words: string[] = [];
  const h = Math.floor(n / 100);
  const t = Math.floor((n % 100) / 10);
  const u = n % 10;
  if (h) words.push(HUNDREDS[h]);
  if (t === 1) words.push(TEENS[u]);
  else {
    if (t) words.push(TENS[t]);
    if (u) words.push((feminine ? UNITS_F : UNITS_M)[u]);
  }
  return words.join(" ");
}

const SCALES: { forms: [string, string, string]; feminine: boolean }[] = [
  { forms: ["рубль", "рубля", "рублей"], feminine: false },
  { forms: ["тысяча", "тысячи", "тысяч"], feminine: true },
  { forms: ["миллион", "миллиона", "миллионов"], feminine: false },
  { forms: ["миллиард", "миллиарда", "миллиардов"], feminine: false },
];

/** 1594.5 → «Одна тысяча пятьсот девяносто четыре рубля 50 копеек». Как пишут в счетах. */
export function amountInWords(amount: number): string {
  const kopecks = Math.round(Math.abs(amount) * 100);
  let rubles = Math.floor(kopecks / 100);
  const kop = kopecks % 100;
  const rubleWord = plural(rubles, SCALES[0].forms);
  if (rubles === 0) {
    return `Ноль рублей ${String(kop).padStart(2, "0")} ${plural(kop, ["копейка", "копейки", "копеек"])}`;
  }
  const parts: string[] = [];
  for (let i = 0; rubles > 0 && i < SCALES.length; i++) {
    const triple = rubles % 1000;
    rubles = Math.floor(rubles / 1000);
    if (triple === 0) continue;
    const words = tripleWords(triple, SCALES[i].feminine);
    parts.unshift(i === 0 ? words : `${words} ${plural(triple, SCALES[i].forms)}`);
  }
  const text = `${parts.join(" ")} ${rubleWord} ${String(kop).padStart(2, "0")} ${plural(kop, ["копейка", "копейки", "копеек"])}`;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** 1594.5 → «1 594,50» — суммы в таблице счёта всегда с копейками. */
export function formatMoney(amount: number): string {
  return amount.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).replace(/ /g, " ");
}
