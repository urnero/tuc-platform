"use client";

/**
 * Форма заказа (B06): /order/new?quote=<id расчёта>.
 * Слева — что заказываем (из GET /api/v1/quotes/{id}), справа — контакты, адрес (если курьер),
 * комментарий, согласие на обработку данных → POST /api/v1/orders → страница статуса /order/<token>.
 * Доставку клиент выбрал на шаге расчёта — здесь она только показывается.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { formatPrice } from "@/lib/format";
import {
  EMPTY_FORM,
  needsAddress,
  type Order,
  type OrderForm,
  quoteLoadError,
  toRequest,
  uploadIdFromQuote,
  validateForm,
} from "@/lib/order";
import { DELIVERY_LABELS, POSTPROCESS_LABELS, type Quote, quoteLines } from "@/lib/pricing";

const fieldStyle = { borderColor: "var(--muted)", background: "var(--bg)", color: "var(--fg)" };

export default function NewOrderPage() {
  // useSearchParams требует Suspense в Next 15 при сборке статической страницы.
  return (
    <Suspense fallback={<main className="mx-auto max-w-3xl px-4 py-16">Загружаем…</main>}>
      <NewOrder />
    </Suspense>
  );
}

function NewOrder() {
  const router = useRouter();
  const quoteId = useSearchParams().get("quote") ?? "";
  const [quote, setQuote] = useState<Quote | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<OrderForm>(EMPTY_FORM);
  const [errors, setErrors] = useState<ReturnType<typeof validateForm>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!quoteId) {
      setLoadError("Сначала рассчитайте цену модели.");
      return;
    }
    fetch(`/api/v1/quotes/${encodeURIComponent(quoteId)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(quoteLoadError(r.status));
        setQuote((await r.json()) as Quote);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, [quoteId]);

  function set<K extends keyof OrderForm>(key: K, value: OrderForm[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!quote) return;
    const found = validateForm(form, quote.delivery);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setSending(true);
    setServerError(null);
    try {
      const r = await fetch("/api/v1/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toRequest(form, quote.id)),
      });
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { detail?: unknown };
        throw new Error(typeof body.detail === "string" ? body.detail : `Ошибка ${r.status}.`);
      }
      const order = (await r.json()) as Order;
      router.push(`/order/${order.token}`);
    } catch (err) {
      setServerError((err as Error).message);
      setSending(false);
    }
  }

  if (loadError) {
    // Расчёт устарел или не найден: ведём обратно к модели, если по id расчёта понятно, к какой.
    const uploadId = uploadIdFromQuote(quoteId);
    return (
      <main className="mx-auto max-w-3xl px-4 py-16">
        <p role="alert">{loadError}</p>
        <Link href={uploadId ? `/upload/${uploadId}` : "/upload"} style={{ color: "var(--accent)" }}>
          {uploadId ? "← К модели и расчёту цены" : "← Загрузить модель"}
        </Link>
      </main>
    );
  }
  if (!quote) return <main className="mx-auto max-w-3xl px-4 py-16">Загружаем…</main>;

  const courier = needsAddress(quote.delivery);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-16">
      <Link href={`/upload/${quote.upload_id}`} className="text-sm" style={{ color: "var(--accent)" }}>
        ← Назад к модели
      </Link>
      <h1 className="text-2xl font-bold leading-tight">Оформление заказа</h1>

      <section className="flex flex-col gap-3 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
        <h2 className="text-lg font-semibold">Что заказываем</h2>
        <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
          <dt style={{ color: "var(--muted)" }}>Модель</dt>
          <dd className="truncate text-right">{quote.original_name ?? quote.upload_id}</dd>
          <dt style={{ color: "var(--muted)" }}>Материал</dt>
          <dd className="text-right">
            {quote.material}
            {quote.supports ? ", с поддержками" : ""}
          </dd>
          <dt style={{ color: "var(--muted)" }}>Тираж</dt>
          <dd className="text-right">{quote.qty} шт</dd>
          <dt style={{ color: "var(--muted)" }}>Постобработка</dt>
          <dd className="text-right">{POSTPROCESS_LABELS[quote.postprocess] ?? quote.postprocess}</dd>
          <dt style={{ color: "var(--muted)" }}>Получение</dt>
          <dd className="text-right">{DELIVERY_LABELS[quote.delivery] ?? quote.delivery}</dd>
          {quoteLines(quote).map((line) => (
            <div key={line.label} className="contents">
              <dt style={{ color: "var(--muted)" }}>{line.label}</dt>
              <dd className="text-right">{line.value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-2xl font-bold" data-testid="total">
          {formatPrice(quote.total)}
        </p>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Цена предварительная: менеджер подтвердит её перед печатью. Оплата — после подтверждения.
        </p>
      </section>

      <form onSubmit={(e) => void submit(e)} noValidate className="flex flex-col gap-4 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
        <h2 className="text-lg font-semibold">Контакты</h2>

        <Field label="Имя" error={errors.name}>
          <input
            name="name"
            autoComplete="name"
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            className="w-full rounded-md border px-3 py-2"
            style={fieldStyle}
          />
        </Field>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Телефон" error={errors.phone}>
            <input
              name="phone"
              type="tel"
              autoComplete="tel"
              placeholder="+7 999 123-45-67"
              value={form.phone}
              onChange={(e) => set("phone", e.target.value)}
              className="w-full rounded-md border px-3 py-2"
              style={fieldStyle}
            />
          </Field>
          <Field label="E-mail (необязательно)" error={errors.email}>
            <input
              name="email"
              type="email"
              autoComplete="email"
              value={form.email}
              onChange={(e) => set("email", e.target.value)}
              className="w-full rounded-md border px-3 py-2"
              style={fieldStyle}
            />
          </Field>
        </div>

        {courier && (
          <Field label="Адрес доставки" error={errors.address}>
            <input
              name="address"
              autoComplete="street-address"
              placeholder="Москва, улица, дом, квартира"
              value={form.address}
              onChange={(e) => set("address", e.target.value)}
              className="w-full rounded-md border px-3 py-2"
              style={fieldStyle}
            />
          </Field>
        )}

        <Field label="Комментарий (необязательно)">
          <textarea
            name="comment"
            rows={3}
            placeholder="Цвет, срок, особенности модели"
            value={form.comment}
            onChange={(e) => set("comment", e.target.value)}
            className="w-full rounded-md border px-3 py-2"
            style={fieldStyle}
          />
        </Field>

        <label className="flex items-start gap-2 text-sm">
          <input
            name="consent"
            type="checkbox"
            checked={form.consent}
            onChange={(e) => set("consent", e.target.checked)}
            className="mt-1"
          />
          <span>
            Согласен с условиями{" "}
            <Link href="/offer" target="_blank" className="underline underline-offset-2">
              оферты
            </Link>{" "}
            и обработкой персональных данных (
            <Link href="/policy" target="_blank" className="underline underline-offset-2">
              политика
            </Link>
            ).
            {errors.consent && (
              <>
                <br />
                <span role="alert">{errors.consent}</span>
              </>
            )}
          </span>
        </label>

        {serverError && <p role="alert">{serverError}</p>}

        <button
          type="submit"
          disabled={sending}
          className="self-start rounded-md px-5 py-2 font-medium disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--bg)" }}
        >
          {sending ? "Отправляем…" : `Заказать за ${formatPrice(quote.total)}`}
        </button>
      </form>
    </main>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span style={{ color: "var(--muted)" }}>{label}</span>
      {children}
      {error && <span role="alert">{error}</span>}
    </label>
  );
}
