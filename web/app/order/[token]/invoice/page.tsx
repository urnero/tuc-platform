"use client";

/**
 * Счёт на оплату для организации (B33): /order/<token>/invoice.
 * Данные — GET /api/v1/orders/{token} (реквизиты покупателя лежат в заказе), реквизиты студии —
 * lib/company.ts. Страница свёрстана под печать на A4: кнопка «Распечатать» → в диалоге браузера
 * «Сохранить как PDF». Пока владелец не заполнил банковские реквизиты в company.ts, сверху
 * предупреждение — такой счёт оплатить нельзя.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { COMPANY } from "@/lib/company";
import {
  amountInWords,
  formatMoney,
  invoiceDate,
  invoiceLines,
  invoiceNumber,
  paymentPurpose,
  plural,
  sellerRequisites,
} from "@/lib/invoice";
import { type Order, paysByInvoice } from "@/lib/order";

// Счёт печатается на белой бумаге: цвета фиксированные, тема сайта тут не нужна.
const paper = { background: "#fff", color: "#111" };
const cell = { border: "1px solid #111", padding: "4px 8px", fontSize: 13 } as const;

export default function InvoicePage() {
  const { token } = useParams<{ token: string }>();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/v1/orders/${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "Заказ не найден. Проверьте ссылку." : `Ошибка ${r.status}.`);
        const o = (await r.json()) as Order;
        if (!paysByInvoice(o) || !o.company) throw new Error("По этому заказу счёт не выставляется: он оплачивается онлайн.");
        setOrder(o);
      })
      .catch((e: Error) => setError(e.message));
  }, [token]);

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-16">
        <p role="alert">{error}</p>
        <Link href={`/order/${encodeURIComponent(token)}`} style={{ color: "var(--accent)" }}>
          ← К заказу
        </Link>
      </main>
    );
  }
  if (!order || !order.company) return <main className="mx-auto max-w-3xl px-4 py-16">Загружаем…</main>;

  const seller = sellerRequisites(COMPANY);
  const buyer = order.company;
  const lines = invoiceLines(order);
  const number = invoiceNumber(order);
  const date = invoiceDate(order.created_at);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-8">
      {/* На бумаге — только сам счёт, без шапки и подвала сайта */}
      <style>{`@media print { body > header, body > footer, nav { display: none !important; } }`}</style>
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm print:hidden">
        <Link href={`/order/${encodeURIComponent(token)}`} style={{ color: "var(--accent)" }}>
          ← К заказу {order.number}
        </Link>
        <button
          type="button"
          onClick={() => window.print()}
          className="rounded-md px-4 py-2 font-medium"
          style={{ background: "var(--accent)", color: "var(--bg)" }}
        >
          Распечатать или сохранить в PDF
        </button>
      </div>

      {seller.missing.length > 0 && (
        <p className="rounded-md border px-4 py-3 text-sm print:hidden" role="alert" style={{ borderColor: "var(--muted)" }}>
          Счёт ещё нельзя оплатить: студия не указала {seller.missing.join(", ")}. Напишите нам — пришлём счёт с реквизитами.
        </p>
      )}

      <article className="rounded-md border p-6 print:border-0 print:p-0" style={paper} data-testid="invoice-doc">
        {/* Шапка: банковские реквизиты получателя — как в типовом счёте */}
        <table className="w-full border-collapse">
          <tbody>
            <tr>
              <td style={{ ...cell, width: "50%" }} rowSpan={2}>
                <span style={{ fontSize: 11 }}>Банк получателя</span>
                <br />
                {seller.bankName}
              </td>
              <td style={{ ...cell, width: "10%" }}>БИК</td>
              <td style={cell}>{seller.bik}</td>
            </tr>
            <tr>
              <td style={cell}>Сч. №</td>
              <td style={cell}>{seller.corrAccount}</td>
            </tr>
            <tr>
              <td style={cell}>
                ИНН {seller.inn}
                {seller.ogrnip ? ` · ОГРНИП ${seller.ogrnip}` : ""}
              </td>
              <td style={cell} rowSpan={2}>
                Сч. №
              </td>
              <td style={cell} rowSpan={2}>
                {seller.account}
              </td>
            </tr>
            <tr>
              <td style={cell}>
                <span style={{ fontSize: 11 }}>Получатель</span>
                <br />
                {seller.name}
              </td>
            </tr>
          </tbody>
        </table>

        <h1 className="mt-6 text-xl font-bold">
          Счёт на оплату № {number} от {date}
        </h1>
        <hr className="my-3" style={{ borderColor: "#111" }} />

        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="font-semibold">Поставщик:</dt>
          <dd>
            {seller.name}, ИНН {seller.inn}
            {seller.ogrnip ? `, ОГРНИП ${seller.ogrnip}` : ""}, {seller.address}
            {seller.phone ? `, тел. ${seller.phone}` : ""}
          </dd>
          <dt className="font-semibold">Покупатель:</dt>
          <dd data-testid="buyer">
            {buyer.name}, ИНН {buyer.inn}
            {buyer.kpp ? `, КПП ${buyer.kpp}` : ""}
            {buyer.address ? `, ${buyer.address}` : ""}
          </dd>
          <dt className="font-semibold">Основание:</dt>
          <dd>
            заказ {order.number} на сайте, публичная оферта (страница /offer сайта)
          </dd>
        </dl>

        <table className="mt-4 w-full border-collapse">
          <thead>
            <tr>
              <th style={cell}>№</th>
              <th style={{ ...cell, textAlign: "left" }}>Товары (работы, услуги)</th>
              <th style={cell}>Кол-во</th>
              <th style={cell}>Ед.</th>
              <th style={cell}>Цена</th>
              <th style={cell}>Сумма</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={l.title}>
                <td style={{ ...cell, textAlign: "center" }}>{i + 1}</td>
                <td style={cell}>{l.title}</td>
                <td style={{ ...cell, textAlign: "right" }}>{l.qty}</td>
                <td style={{ ...cell, textAlign: "center" }}>{l.unit}</td>
                <td style={{ ...cell, textAlign: "right", whiteSpace: "nowrap" }}>{formatMoney(l.price)}</td>
                <td style={{ ...cell, textAlign: "right", whiteSpace: "nowrap" }}>{formatMoney(l.sum)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="mt-3 flex flex-col items-end gap-1 text-sm">
          <p>
            Итого: <b>{formatMoney(order.total)}</b>
          </p>
          <p>Без НДС</p>
          <p>
            Всего к оплате: <b data-testid="invoice-total">{formatMoney(order.total)}</b>
          </p>
        </div>

        <p className="mt-4 text-sm">
          Всего {lines.length} {plural(lines.length, ["наименование", "наименования", "наименований"])}, на сумму {formatMoney(order.total)} руб.
          <br />
          <b>{amountInWords(order.total)}</b>
        </p>

        <p className="mt-4 text-xs" style={{ color: "#444" }}>
          Назначение платежа: {paymentPurpose(order)} Оплата счёта означает согласие с условиями оферты. Срок изготовления
          считается с момента поступления оплаты. Контакты: {seller.email || "см. сайт"}
          {seller.phone ? `, ${seller.phone}` : ""}.
        </p>

        <div className="mt-10 grid grid-cols-2 gap-8 text-sm">
          <p>
            Исполнитель ____________________
            <br />
            <span style={{ fontSize: 11 }}>{seller.name}</span>
          </p>
          <p>
            Заказ оформлен на сайте {date}
            <br />
            <span style={{ fontSize: 11 }}>контактное лицо: {order.customer_name}, {order.email ?? order.phone}</span>
          </p>
        </div>
      </article>
    </main>
  );
}
