"use client";

/**
 * Страница статуса заказа (B06): /order/<token>. Ссылку клиент получает после оформления —
 * её можно сохранить и открыть позже. Данные — GET /api/v1/orders/{token}.
 * Статус меняет владелец (бот B07, админка B09).
 * Оплата (B08): кнопка «Оплатить» → POST /api/v1/orders/{token}/payment → форма ЮKassa.
 * Вернувшись с формы (?payment=check), страница зовёт /payment/check и показывает итог.
 * Заказ от организации (B33) платится по счёту: вместо «Оплатить» — ссылка на счёт
 * /order/<token>/invoice и подсказка про безнал.
 * Уведомления (B34): блок «Когда статус изменится, напишем …» и кнопка «Получать статусы
 * в Telegram» — ссылка на бота с token заказа, бот сам привяжет чат к заказу.
 */

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { reachGoal } from "@/lib/metrika";
import { formatPrice } from "@/lib/format";
import {
  formatDate,
  formatPhone,
  notificationsBlock,
  type Order,
  paysByInvoice,
  STATUS_HINTS,
  STATUS_LABELS,
  STATUS_STEPS,
} from "@/lib/order";
import { canPay, checkResultText, type PaymentCheck, type PaymentStart, paymentHint } from "@/lib/payment";
import { DELIVERY_LABELS, POSTPROCESS_LABELS } from "@/lib/pricing";

export default function OrderPage() {
  // useSearchParams требует Suspense в Next 15 при сборке статической страницы.
  return (
    <Suspense fallback={<main className="mx-auto max-w-3xl px-4 py-16">Загружаем…</main>}>
      <OrderStatus />
    </Suspense>
  );
}

function OrderStatus() {
  const { token } = useParams<{ token: string }>();
  const returnedFromPayment = useSearchParams().get("payment") === "check";
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [payError, setPayError] = useState<string | null>(null);
  const [payResult, setPayResult] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);

  async function loadOrder(): Promise<Order> {
    const r = await fetch(`/api/v1/orders/${encodeURIComponent(token)}`);
    if (!r.ok) throw new Error(r.status === 404 ? "Заказ не найден. Проверьте ссылку." : `Ошибка ${r.status}.`);
    return (await r.json()) as Order;
  }

  // B51: цель «оплата» — один раз за сессию вкладки на заказ
  useEffect(() => {
    if (order?.status === "paid") reachGoal("paid", order.token);
  }, [order]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (returnedFromPayment) {
          // Клиент вернулся с формы ЮKassa: сверяем платёж, потом показываем заказ.
          const c = await fetch(`/api/v1/orders/${encodeURIComponent(token)}/payment/check`, { method: "POST" });
          if (c.ok && !cancelled) setPayResult(checkResultText((await c.json()) as PaymentCheck));
        }
        const o = await loadOrder();
        if (!cancelled) setOrder(o);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, returnedFromPayment]);

  async function pay() {
    setPaying(true);
    setPayError(null);
    try {
      const r = await fetch(`/api/v1/orders/${encodeURIComponent(token)}/payment`, { method: "POST" });
      const body = (await r.json()) as PaymentStart & { detail?: string };
      if (!r.ok) throw new Error(body.detail ?? `Ошибка ${r.status}.`);
      if (!body.confirmation_url) throw new Error("ЮKassa не дала ссылку на оплату. Попробуйте ещё раз.");
      window.location.assign(body.confirmation_url);
    } catch (e) {
      setPayError((e as Error).message);
      setPaying(false);
    }
  }

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-16">
        <p role="alert">{error}</p>
        <Link href="/upload" style={{ color: "var(--accent)" }}>
          ← Загрузить модель
        </Link>
      </main>
    );
  }
  if (!order) return <main className="mx-auto max-w-3xl px-4 py-16">Загружаем…</main>;

  const stepIndex = STATUS_STEPS.indexOf(order.status);
  const cancelled = order.status === "cancelled";
  const invoice = paysByInvoice(order);
  const notifications = notificationsBlock(order);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-16">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold leading-tight">Заказ {order.number}</h1>
        <span className="text-sm" style={{ color: "var(--muted)" }}>
          от {formatDate(order.created_at)}
        </span>
      </div>

      <section className="flex flex-col gap-4 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
        <p className="text-xl font-semibold" data-testid="status">
          {STATUS_LABELS[order.status] ?? order.status}
        </p>
        {!cancelled && (
          <ol className="flex flex-wrap gap-2 text-xs" aria-label="Этапы заказа">
            {STATUS_STEPS.map((s, i) => (
              <li
                key={s}
                className="rounded-full border px-3 py-1"
                style={
                  i <= stepIndex
                    ? { background: "var(--accent)", color: "var(--bg)", borderColor: "var(--accent)" }
                    : { color: "var(--muted)", borderColor: "var(--muted)" }
                }
              >
                {STATUS_LABELS[s]}
              </li>
            ))}
          </ol>
        )}
        <p className="text-sm">{STATUS_HINTS[order.status]}</p>
        {payResult && (
          <p className="text-sm font-semibold" role="status" data-testid="pay-result">
            {payResult}
          </p>
        )}
        {invoice && order.status === "new" && (
          <div className="flex flex-col gap-2" data-testid="invoice">
            <p className="text-sm" style={{ color: "var(--muted)" }}>
              Заказ от организации: оплата безналом по счёту. Когда деньги поступят, заказ станет «Оплачен» и уйдёт в печать.
            </p>
            <Link
              href={`/order/${encodeURIComponent(token)}/invoice`}
              className="self-start rounded-lg px-5 py-3 text-base font-semibold"
              style={{ background: "var(--accent)", color: "var(--bg)" }}
            >
              Счёт на оплату {order.number}
            </Link>
          </div>
        )}
        {!invoice && paymentHint(order.status, order.payment) && (
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            {paymentHint(order.status, order.payment)}
          </p>
        )}
        {!invoice && canPay(order.status, order.payment) && (
          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={pay}
              disabled={paying}
              data-testid="pay"
              className="rounded-lg px-5 py-3 text-base font-semibold disabled:opacity-50"
              style={{ background: "var(--accent)", color: "var(--bg)" }}
            >
              {paying ? "Переходим к оплате…" : `Оплатить ${formatPrice(order.total)}`}
            </button>
            {payError && (
              <p className="text-sm" role="alert">
                {payError}
              </p>
            )}
          </div>
        )}
        {notifications && (
          <div className="flex flex-wrap items-center gap-3 text-sm" data-testid="notifications">
            <span style={{ color: "var(--muted)" }}>{notifications.text}</span>
            {notifications.telegramLink && (
              <a
                href={notifications.telegramLink}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-lg border px-4 py-2 font-semibold"
                style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
              >
                Получать статусы в Telegram
              </a>
            )}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
        <h2 className="text-lg font-semibold">Состав</h2>
        <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
          <dt style={{ color: "var(--muted)" }}>Модель</dt>
          <dd className="truncate text-right">{order.original_name ?? order.upload_id}</dd>
          <dt style={{ color: "var(--muted)" }}>Материал</dt>
          <dd className="text-right">
            {order.material}
            {order.supports ? ", с поддержками" : ""}
          </dd>
          <dt style={{ color: "var(--muted)" }}>Тираж</dt>
          <dd className="text-right">{order.qty} шт</dd>
          <dt style={{ color: "var(--muted)" }}>Постобработка</dt>
          <dd className="text-right">{POSTPROCESS_LABELS[order.postprocess] ?? order.postprocess}</dd>
          <dt style={{ color: "var(--muted)" }}>Получение</dt>
          <dd className="text-right">{DELIVERY_LABELS[order.delivery] ?? order.delivery}</dd>
          {order.address && (
            <>
              <dt style={{ color: "var(--muted)" }}>Адрес</dt>
              <dd className="text-right">{order.address}</dd>
            </>
          )}
        </dl>
        <p className="text-2xl font-bold" data-testid="total">
          {formatPrice(order.total)}
        </p>
      </section>

      <section className="flex flex-col gap-3 rounded-lg border p-6 text-sm" style={{ borderColor: "var(--muted)" }}>
        <h2 className="text-lg font-semibold">Контакты</h2>
        {order.anonymized_at && (
          <p style={{ color: "var(--muted)" }}>
            С выполнения заказа прошло больше 5 лет — имя, телефон, e-mail и адрес из него удалены (политика обработки
            персональных данных, раздел 6).
          </p>
        )}
        <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1">
          <dt style={{ color: "var(--muted)" }}>Имя</dt>
          <dd className="text-right">{order.customer_name}</dd>
          <dt style={{ color: "var(--muted)" }}>Телефон</dt>
          <dd className="text-right">{formatPhone(order.phone)}</dd>
          {order.email && (
            <>
              <dt style={{ color: "var(--muted)" }}>E-mail</dt>
              <dd className="text-right">{order.email}</dd>
            </>
          )}
        </dl>
        {order.company && (
          <p>
            Покупатель: {order.company.name}, ИНН {order.company.inn}
            {order.company.kpp ? `, КПП ${order.company.kpp}` : ""}
            {invoice && order.status !== "new" && (
              <>
                {" · "}
                <Link href={`/order/${encodeURIComponent(token)}/invoice`} className="underline underline-offset-2">
                  счёт {order.number}
                </Link>
              </>
            )}
          </p>
        )}
        {order.comment && <p>Комментарий: {order.comment}</p>}
        <p style={{ color: "var(--muted)" }}>
          Сохраните ссылку на эту страницу — по ней видно, что с заказом. Вопросы — по телефону или в Telegram студии.
          {order.email && (
            <>
              {" "}
              Все заказы на {order.email} — в{" "}
              <Link href="/account" className="underline underline-offset-2">
                кабинете
              </Link>
              .
            </>
          )}
        </p>
      </section>

      <Link href="/upload" className="text-sm" style={{ color: "var(--accent)" }}>
        Заказать ещё одну модель →
      </Link>
    </main>
  );
}
