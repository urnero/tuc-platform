"use client";

/**
 * Страница статуса заказа (B06): /order/<token>. Ссылку клиент получает после оформления —
 * её можно сохранить и открыть позже. Данные — GET /api/v1/orders/{token}.
 * Статус меняет владелец (бот B07, админка B09); оплата (B08) появится здесь кнопкой.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { formatPrice } from "@/lib/format";
import { formatDate, formatPhone, type Order, STATUS_HINTS, STATUS_LABELS, STATUS_STEPS } from "@/lib/order";
import { DELIVERY_LABELS, POSTPROCESS_LABELS } from "@/lib/pricing";

export default function OrderPage() {
  const { token } = useParams<{ token: string }>();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/v1/orders/${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "Заказ не найден. Проверьте ссылку." : `Ошибка ${r.status}.`);
        setOrder((await r.json()) as Order);
      })
      .catch((e: Error) => setError(e.message));
  }, [token]);

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
        {order.status === "new" && (
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            Оплата онлайн появится после подтверждения заказа менеджером.
          </p>
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
        {order.comment && <p>Комментарий: {order.comment}</p>}
        <p style={{ color: "var(--muted)" }}>
          Сохраните ссылку на эту страницу — по ней видно, что с заказом. Вопросы — по телефону или в Telegram студии.
        </p>
      </section>

      <Link href="/upload" className="text-sm" style={{ color: "var(--accent)" }}>
        Заказать ещё одну модель →
      </Link>
    </main>
  );
}
