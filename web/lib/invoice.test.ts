import { describe, expect, it } from "vitest";
import { COMPANY } from "./company";
import {
  amountInWords,
  formatMoney,
  invoiceDate,
  invoiceLines,
  invoiceNumber,
  paymentPurpose,
  plural,
  sellerRequisites,
} from "./invoice";
import type { Order } from "./order";
import type { Quote } from "./pricing";

const quote: Quote = {
  id: "a-1",
  upload_id: "a",
  original_name: "box.stl",
  created_at: "2026-10-26T21:10:00+00:00",
  currency: "RUB",
  material: "PLA",
  tech: "FDM",
  supports: false,
  qty: 5,
  postprocess: "sanding",
  delivery: "courier_moscow",
  material_g: 50,
  print_time_s: 7200,
  price_per_g: 4,
  machine_rate: 120,
  k_supports: 1,
  k_batch: 1,
  margin: 0.35,
  min_order: 500,
  material_cost: 1000,
  machine_cost: 1200,
  unit_price: 594.37,
  print_subtotal: 2971.85,
  min_order_applied: false,
  postprocess_cost: 750,
  delivery_cost: 400,
  total: 4122,
};

const order: Order = {
  id: 12,
  number: "ТУЦ-12",
  token: "t",
  status: "new",
  created_at: "2026-10-26T21:10:00+00:00",
  updated_at: "2026-10-26T21:10:00+00:00",
  customer_name: "Иван",
  phone: "+79991234567",
  email: "buh@romashka.ru",
  delivery: "courier_moscow",
  address: "Тверская, 1",
  comment: null,
  company: { name: "ООО «Ромашка»", inn: "7707083893", kpp: "770101001", address: null },
  payment_method: "invoice",
  upload_id: "a",
  quote_id: "a-1",
  original_name: "box.stl",
  material: "PLA",
  supports: false,
  qty: 5,
  postprocess: "sanding",
  total: 4122,
  currency: "RUB",
  quote,
};

describe("invoiceLines", () => {
  it("печать × тираж, постобработка за штуку, доставка за заказ; таблица сходится с суммой заказа", () => {
    const lines = invoiceLines(order);
    expect(lines.map((l) => l.title)).toEqual(["3D-печать (PLA): box.stl", "Постобработка: шлифовка", "Курьер по Москве"]);
    expect(lines[1]).toMatchObject({ qty: 5, unit: "шт", price: 150, sum: 750 });
    expect(lines[2]).toMatchObject({ qty: 1, unit: "усл.", sum: 400 });
    // 2971,85 + 750 + 400 = 4121,85, а заказ на 4122 ₽ — 15 копеек ушли в строку печати.
    expect(lines[0].sum).toBe(2972);
    expect(lines.reduce((a, l) => a + l.sum, 0)).toBe(order.total);
  });
  it("минимальный заказ — одна строка «усл.» на его сумму", () => {
    const small: Order = {
      ...order,
      qty: 1,
      postprocess: "none",
      delivery: "pickup",
      total: 500,
      quote: { ...quote, qty: 1, unit_price: 120, print_subtotal: 120, min_order_applied: true, postprocess_cost: 0, delivery_cost: 0, total: 500 },
    };
    const lines = invoiceLines(small);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({ qty: 1, unit: "усл.", sum: 500 });
    expect(lines[0].title).toContain("минимальный заказ");
  });
  it("поддержки попадают в название позиции", () => {
    expect(invoiceLines({ ...order, supports: true })[0].title).toBe("3D-печать (PLA, с поддержками): box.stl");
  });
});

describe("шапка счёта", () => {
  it("номер счёта = номер заказа, дата по Москве, назначение платежа", () => {
    expect(invoiceNumber(order)).toBe("ТУЦ-12");
    expect(invoiceDate(order.created_at)).toBe("27 октября 2026 г.");
    expect(paymentPurpose(order)).toBe("Оплата по счёту № ТУЦ-12 от 27 октября 2026 г. за услуги 3D-печати. Без НДС.");
  });
  it("реквизиты студии в репозитории пусты — список недостающих не пуст, в полях заглушка", () => {
    const s = sellerRequisites(COMPANY);
    expect(s.missing).toContain("расчётный счёт");
    expect(s.bik).toBe("уточняется");
  });
  it("когда банк заполнен — недостающих нет", () => {
    const s = sellerRequisites({
      ...COMPANY,
      legalName: "ИП Иванов И. И.",
      inn: "500100732259",
      legalAddress: "Москва",
      bankName: "АО «Банк»",
      bik: "044525974",
      bankAccount: "40802810000000000001",
      corrAccount: "30101810145250000974",
    });
    expect(s.missing).toEqual([]);
    expect(s.account).toBe("40802810000000000001");
  });
});

describe("сумма прописью", () => {
  it("plural", () => {
    expect([1, 2, 5, 11, 21, 22, 25, 101, 111].map((n) => plural(n, ["рубль", "рубля", "рублей"]))).toEqual([
      "рубль", "рубля", "рублей", "рублей", "рубль", "рубля", "рублей", "рубль", "рублей",
    ]);
  });
  it("рубли и копейки, тысячи — женский род", () => {
    expect(amountInWords(4122)).toBe("Четыре тысячи сто двадцать два рубля 00 копеек");
    expect(amountInWords(1594.5)).toBe("Одна тысяча пятьсот девяносто четыре рубля 50 копеек");
    expect(amountInWords(21001.01)).toBe("Двадцать одна тысяча один рубль 01 копейка");
    expect(amountInWords(500)).toBe("Пятьсот рублей 00 копеек");
    expect(amountInWords(1000000)).toBe("Один миллион рублей 00 копеек");
    expect(amountInWords(2000012)).toBe("Два миллиона двенадцать рублей 00 копеек");
    expect(amountInWords(0.5)).toBe("Ноль рублей 50 копеек");
    expect(amountInWords(11)).toBe("Одиннадцать рублей 00 копеек");
  });
  it("formatMoney — с копейками и пробелами между разрядами", () => {
    expect(formatMoney(4122)).toBe("4 122,00");
    expect(formatMoney(594.37)).toBe("594,37");
  });
});
