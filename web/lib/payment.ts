/** Оплата ЮKassa (B08): блок `payment` в ответе заказа и логика кнопки «Оплатить». */

import type { OrderStatus } from "./order";

export type PaymentStatus = "pending" | "waiting_for_capture" | "succeeded" | "canceled";

/** Поле `payment` в GET /api/v1/orders/{token}. */
export type PaymentInfo = {
  enabled: boolean; // подключена ли онлайн-оплата (ключи ЮKassa заданы на сервере)
  status: PaymentStatus | null; // последний платёж по заказу; null — оплату не начинали
  confirmation_url: string | null; // ссылка на форму ЮKassa, пока платёж «pending»
  paid_at: string | null;
};

/** Ответ POST /api/v1/orders/{token}/payment. */
export type PaymentStart = {
  payment: { yookassa_id: string; status: PaymentStatus; amount: number };
  confirmation_url: string | null;
};

/** Ответ POST /api/v1/orders/{token}/payment/check. */
export type PaymentCheck = {
  payment: { status: PaymentStatus; paid_at: string | null };
  order_status: OrderStatus;
};

/** Показывать ли кнопку «Оплатить»: оплата включена, заказ «принят», успешного платежа нет. */
export function canPay(orderStatus: OrderStatus, payment: PaymentInfo | undefined): boolean {
  if (!payment || !payment.enabled) return false;
  if (orderStatus !== "new") return false;
  return payment.status !== "succeeded";
}

/** Что сказать клиенту под статусом заказа про оплату. */
export function paymentHint(orderStatus: OrderStatus, payment: PaymentInfo | undefined): string | null {
  if (orderStatus !== "new") return null;
  if (!payment || !payment.enabled) {
    return "Оплата онлайн появится после подтверждения заказа менеджером.";
  }
  if (payment.status === "pending") return "Платёж начат, но ещё не завершён. Можно продолжить оплату.";
  if (payment.status === "canceled") return "Платёж не прошёл или был отменён. Попробуйте ещё раз.";
  return "Оплатите заказ онлайн — картой, СБП или ЮMoney. После оплаты поставим модель в печать.";
}

/** Текст после возврата с формы ЮKassa (?payment=check). */
export function checkResultText(check: PaymentCheck): string {
  if (check.payment.status === "succeeded") return "Оплата прошла. Спасибо!";
  if (check.payment.status === "canceled") return "Оплата не прошла. Можно попробовать ещё раз.";
  return "Платёж ещё обрабатывается. Обновите страницу через минуту.";
}
