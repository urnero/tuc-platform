"use client";

/**
 * Форма заказа (B06): /order/new?quote=<id расчёта>.
 * Слева — что заказываем (из GET /api/v1/quotes/{id}), справа — контакты, адрес (если курьер),
 * комментарий, согласие на обработку данных → POST /api/v1/orders → страница статуса /order/<token>.
 * Доставку клиент выбрал на шаге расчёта — здесь она только показывается.
 * Если клиент вошёл в кабинет (B32), имя, телефон, e-mail и адрес подставляются
 * из последнего заказа (GET /api/v1/account) — поля остаются редактируемыми.
 * Галочка «Заказ от организации или ИП» (B33) открывает реквизиты покупателя: такой заказ
 * оплачивается по счёту безналом, счёт появится на странице заказа.
 * UX (B42): маска телефона на лету, проверка поля при уходе с него (и сразу после исправления),
 * комментарий спрятан за ссылкой, итог заказа всегда на виду — справа на компьютере (липкий блок)
 * и панелью с кнопкой «Заказать» внизу экрана на телефоне. Ошибки сервера — lib/errors.ts.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import type { Account } from "@/lib/account";
import { Field } from "@/components/ui";
import { caughtErrorText, responseErrorText } from "@/lib/errors";
import { reachGoal } from "@/lib/metrika";
import { formatPrice } from "@/lib/format";
import {
  EMPTY_FORM,
  innKind,
  liveFieldError,
  maskPhone,
  needsAddress,
  type Order,
  type OrderForm,
  prefillForm,
  quoteLoadError,
  toRequest,
  uploadIdFromQuote,
  validateForm,
} from "@/lib/order";
import { DELIVERY_LABELS, POSTPROCESS_LABELS, type Quote, quoteLines } from "@/lib/pricing";

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
  const [showComment, setShowComment] = useState(false);

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
      .catch((e: unknown) => setLoadError(caughtErrorText(e)));
  }, [quoteId]);

  // Клиент в кабинете — заполняем контакты из прошлого заказа (пустые поля, пока ничего не ввели).
  useEffect(() => {
    // Без расчёта форма не откроется — незачем звать кабинет (гостю он отвечает 401 в консоль).
    if (!quoteId) return;
    fetch("/api/v1/account")
      .then(async (r) => (r.ok ? ((await r.json()) as Account) : null))
      .then((a) => a && setForm((f) => prefillForm(f, a)))
      .catch(() => {});
  }, [quoteId]);

  const delivery = quote?.delivery ?? "pickup";

  function set<K extends keyof OrderForm>(key: K, value: OrderForm[K]) {
    const next = { ...form, [key]: value };
    setForm(next);
    // Поле уже было с ошибкой — перепроверяем при вводе, чтобы ошибка исчезла, как только исправили.
    setErrors((e) => (e[key] ? { ...e, [key]: liveFieldError(next, delivery, key, true) } : e));
  }

  /** Ушли с поля — проверяем его (пустое не ругаем, это скажем при отправке). */
  function check(key: keyof OrderForm) {
    setErrors((e) => ({ ...e, [key]: liveFieldError(form, delivery, key) }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!quote) return;
    const found = validateForm(form, quote.delivery);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      // Ставим курсор в первое поле с ошибкой (после того как React отрисует подсветку).
      setTimeout(() => document.querySelector<HTMLElement>('#order-form [aria-invalid="true"], #order-form [role="alert"]')?.focus(), 0);
      return;
    }
    setSending(true);
    setServerError(null);
    try {
      const r = await fetch("/api/v1/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toRequest(form, quote.id)),
      });
      if (!r.ok) throw new Error(await responseErrorText(r));
      const order = (await r.json()) as Order;
      reachGoal("order");
      router.push(`/order/${order.token}`);
    } catch (err) {
      setServerError(caughtErrorText(err));
      setSending(false);
    }
  }

  if (loadError) {
    // Расчёт устарел или не найден: ведём обратно к модели, если по id расчёта понятно, к какой.
    const uploadId = uploadIdFromQuote(quoteId);
    return (
      <main className="mx-auto max-w-3xl px-4 py-16">
        <h1 className="mb-4 text-2xl font-semibold">Оформление заказа</h1>
        <p role="alert">{loadError}</p>
        <Link href={uploadId ? `/upload/${uploadId}` : "/upload"} style={{ color: "var(--filament-text)" }}>
          {uploadId ? "← К модели и расчёту цены" : "← Загрузить модель"}
        </Link>
      </main>
    );
  }
  if (!quote)
    return (
      <main className="mx-auto max-w-3xl px-4 py-16">
        <h1 className="mb-4 text-2xl font-semibold">Оформление заказа</h1>
        <p>Загружаем…</p>
      </main>
    );

  const courier = needsAddress(quote.delivery);
  const submitText = sending
    ? "Отправляем…"
    : form.b2b
      ? `Заказать и получить счёт на ${formatPrice(quote.total)}`
      : `Заказать за ${formatPrice(quote.total)}`;

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 pb-28 pt-10 lg:pb-16">
      <Link href={`/upload/${quote.upload_id}`} className="text-sm" style={{ color: "var(--filament-text)" }}>
        ← Назад к модели
      </Link>
      <h1 className="text-2xl font-bold leading-tight">Оформление заказа</h1>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        <section className="card flex flex-col gap-3 lg:sticky lg:top-24 lg:order-2" data-testid="summary">
          <h2 className="text-lg font-semibold">Ваш заказ</h2>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
            <dt style={{ color: "var(--ink-muted)" }}>Модель</dt>
            <dd className="truncate text-right">{quote.original_name ?? quote.upload_id}</dd>
            <dt style={{ color: "var(--ink-muted)" }}>Материал</dt>
            <dd className="text-right">
              {quote.material}
              {quote.supports ? ", с поддержками" : ""}
            </dd>
            <dt style={{ color: "var(--ink-muted)" }}>Тираж</dt>
            <dd className="text-right">{quote.qty} шт</dd>
            <dt style={{ color: "var(--ink-muted)" }}>Постобработка</dt>
            <dd className="text-right">{POSTPROCESS_LABELS[quote.postprocess] ?? quote.postprocess}</dd>
            <dt style={{ color: "var(--ink-muted)" }}>Получение</dt>
            <dd className="text-right">{DELIVERY_LABELS[quote.delivery] ?? quote.delivery}</dd>
          </dl>
          <details className="text-sm">
            <summary className="cursor-pointer" style={{ color: "var(--filament-text)" }}>
              Из чего складывается цена
            </summary>
            <dl className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1">
              {quoteLines(quote).map((line) => (
                <div key={line.label} className="contents">
                  <dt style={{ color: "var(--ink-muted)" }}>{line.label}</dt>
                  <dd className="text-right">{line.value}</dd>
                </div>
              ))}
            </dl>
          </details>
          <p className="text-2xl font-bold" data-testid="total">
            {formatPrice(quote.total)}
          </p>
          {quote.k_batch < 1 && (
            <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
              В цене учтена скидка за тираж −{Math.round((1 - quote.k_batch) * 100)} %.
            </p>
          )}
          <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
            Цена предварительная: менеджер подтвердит её перед печатью. Оплата — после подтверждения.
          </p>
        </section>

        <form
          id="order-form"
          onSubmit={(e) => void submit(e)}
          noValidate
          className="card flex flex-col gap-4 lg:order-1"
        >
          <h2 className="text-lg font-semibold">Контакты</h2>

          <Field
            id="order-name"
            label="Имя"
            name="name"
            autoComplete="name"
            value={form.name}
            error={errors.name}
            onChange={(e) => set("name", e.target.value)}
            onBlur={() => check("name")}
          />

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field
              id="order-phone"
              label="Телефон"
              name="phone"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              placeholder="+7 999 123-45-67"
              value={form.phone}
              error={errors.phone}
              onChange={(e) => set("phone", maskPhone(e.target.value))}
              onBlur={() => check("phone")}
            />
            <Field
              id="order-email"
              label={form.b2b ? "E-mail (для счёта)" : "E-mail (необязательно)"}
              hint={form.b2b ? undefined : "Пришлём статус заказа"}
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              value={form.email}
              error={errors.email}
              onChange={(e) => set("email", e.target.value.trim())}
              onBlur={() => check("email")}
            />
          </div>

          {courier && (
            <Field
              id="order-address"
              label={delivery === "cdek" ? "Город и адрес пункта СДЭК" : "Адрес доставки"}
              name="address"
              autoComplete="street-address"
              placeholder={delivery === "cdek" ? "Казань, ул. Баумана, 1 — пункт СДЭК" : "Москва, улица, дом, квартира"}
              value={form.address}
              error={errors.address}
              onChange={(e) => set("address", e.target.value)}
              onBlur={() => check("address")}
            />
          )}

          <label className="flex items-start gap-2 text-sm">
            <input
              name="b2b"
              type="checkbox"
              checked={form.b2b}
              onChange={(e) => set("b2b", e.target.checked)}
              className="mt-1"
              data-testid="b2b"
            />
            <span>
              Заказ от организации или ИП — оплата по счёту (безнал).
              <span style={{ color: "var(--ink-muted)" }}> Счёт появится на странице заказа сразу после оформления.</span>
            </span>
          </label>

          {form.b2b && (
            <div className="flex flex-col gap-4 rounded-md border p-4" style={{ borderColor: "var(--line)" }} data-testid="company">
              <Field
                id="order-company"
                label="Наименование"
                name="companyName"
                autoComplete="organization"
                placeholder="ООО «Ромашка» или ИП Иванов И. И."
                value={form.companyName}
                error={errors.companyName}
                onChange={(e) => set("companyName", e.target.value)}
                onBlur={() => check("companyName")}
              />
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field
                  id="order-inn"
                  label="ИНН"
                  name="inn"
                  inputMode="numeric"
                  maxLength={12}
                  placeholder="10 цифр у организации, 12 — у ИП"
                  value={form.inn}
                  error={errors.inn}
                  onChange={(e) => set("inn", e.target.value.replace(/\D/g, ""))}
                  onBlur={() => check("inn")}
                />
                {innKind(form.inn) !== "ip" && (
                  <Field
                    id="order-kpp"
                    label="КПП (у организаций)"
                    name="kpp"
                    inputMode="numeric"
                    maxLength={9}
                    placeholder="770101001"
                    value={form.kpp}
                    error={errors.kpp}
                    onChange={(e) => set("kpp", e.target.value.replace(/[^\dA-Za-z]/g, "").toUpperCase())}
                    onBlur={() => check("kpp")}
                  />
                )}
              </div>
              <Field
                id="order-company-address"
                label="Юридический адрес (необязательно)"
                name="companyAddress"
                placeholder="как в документах организации"
                value={form.companyAddress}
                onChange={(e) => set("companyAddress", e.target.value)}
              />
            </div>
          )}

          {showComment || form.comment ? (
            <Field
              id="order-comment"
              multiline
              label="Комментарий (необязательно)"
              name="comment"
              rows={3}
              placeholder="Цвет, срок, особенности модели"
              value={form.comment}
              onChange={(e) => set("comment", e.target.value)}
            />
          ) : (
            <button
              type="button"
              onClick={() => setShowComment(true)}
              className="self-start text-sm underline underline-offset-2"
              style={{ color: "var(--filament-text)" }}
            >
              + Добавить комментарий (цвет, срок)
            </button>
          )}

          <label className="flex items-start gap-2 text-sm">
            <input
              name="consent"
              type="checkbox"
              checked={form.consent}
              onChange={(e) => set("consent", e.target.checked)}
              className="mt-1"
              aria-invalid={errors.consent ? true : undefined}
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
                  <span role="alert" style={{ color: "var(--danger)" }}>
                    {errors.consent}
                  </span>
                </>
              )}
            </span>
          </label>

          {serverError && (
            <p role="alert" style={{ color: "var(--danger)" }}>
              {serverError}
            </p>
          )}

          {/* На компьютере кнопка в форме; на телефоне — в липкой панели внизу (ниже). */}
          <button type="submit" disabled={sending} className="btn btn-primary hidden self-start lg:inline-flex">
            {submitText}
          </button>
        </form>
      </div>

      {/* Телефон и планшет: итог и кнопка всегда на виду. */}
      <div
        className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-between gap-3 border-t px-4 py-3 lg:hidden"
        style={{
          background: "var(--surface-raised)",
          borderColor: "var(--line)",
          paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))",
        }}
        data-testid="sticky-submit"
      >
        <div className="min-w-0 leading-tight">
          <p className="text-lg font-bold">{formatPrice(quote.total)}</p>
          <p className="truncate text-xs" style={{ color: "var(--ink-muted)" }}>
            {quote.material}, {quote.qty} шт · {DELIVERY_LABELS[quote.delivery] ?? quote.delivery}
          </p>
        </div>
        <button type="submit" form="order-form" disabled={sending} className="btn btn-primary shrink-0">
          {sending ? "Отправляем…" : form.b2b ? "Получить счёт" : "Заказать"}
        </button>
      </div>
    </main>
  );
}
