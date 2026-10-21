import { describe, expect, it } from "vitest";
import { canPay, checkResultText, type PaymentInfo, paymentHint } from "./payment";

const off: PaymentInfo = { enabled: false, status: null, confirmation_url: null, paid_at: null };
const fresh: PaymentInfo = { enabled: true, status: null, confirmation_url: null, paid_at: null };
const pending: PaymentInfo = { enabled: true, status: "pending", confirmation_url: "https://yk/1", paid_at: null };
const canceled: PaymentInfo = { enabled: true, status: "canceled", confirmation_url: null, paid_at: null };
const paid: PaymentInfo = { enabled: true, status: "succeeded", confirmation_url: null, paid_at: "2026-10-20T01:02:03+00:00" };

describe("canPay", () => {
  it("кнопка есть только у «принятого» заказа при включённой оплате", () => {
    expect(canPay("new", fresh)).toBe(true);
    expect(canPay("new", pending)).toBe(true);
    expect(canPay("new", canceled)).toBe(true);
  });
  it("без ключей ЮKassa и без блока payment кнопки нет", () => {
    expect(canPay("new", off)).toBe(false);
    expect(canPay("new", undefined)).toBe(false);
  });
  it("оплаченный, печатающийся и отменённый заказ не оплачиваем", () => {
    expect(canPay("new", paid)).toBe(false);
    expect(canPay("paid", fresh)).toBe(false);
    expect(canPay("printing", fresh)).toBe(false);
    expect(canPay("cancelled", fresh)).toBe(false);
  });
});

describe("paymentHint", () => {
  it("объясняет состояние платежа", () => {
    expect(paymentHint("new", off)).toMatch(/менеджером/);
    expect(paymentHint("new", fresh)).toMatch(/картой/);
    expect(paymentHint("new", pending)).toMatch(/продолжить/);
    expect(paymentHint("new", canceled)).toMatch(/ещё раз/);
  });
  it("молчит, когда заказ уже не «принят»", () => {
    expect(paymentHint("paid", paid)).toBeNull();
    expect(paymentHint("cancelled", fresh)).toBeNull();
  });
});

describe("checkResultText", () => {
  it("по результату проверки после возврата с формы", () => {
    expect(checkResultText({ payment: { status: "succeeded", paid_at: "x" }, order_status: "paid" })).toMatch(/Спасибо/);
    expect(checkResultText({ payment: { status: "canceled", paid_at: null }, order_status: "new" })).toMatch(/не прошла/);
    expect(checkResultText({ payment: { status: "pending", paid_at: null }, order_status: "new" })).toMatch(/обрабатывается/);
  });
});
