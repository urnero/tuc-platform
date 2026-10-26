"use client";

/**
 * Кабинет клиента (B32): /account.
 * Не вошёл — форма «e-mail → код из письма» (POST /api/v1/account/login, …/login/confirm).
 * Вошёл — история заказов (GET /api/v1/account/orders): номер, дата, модель, параметры, сумма,
 * статус, ссылка на страницу заказа и кнопка «Повторить» — страница модели с теми же
 * параметрами (lib/account.ts: repeatHref). Выход — POST /api/v1/account/logout.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  type Account,
  type AccountOrder,
  cleanCode,
  type LoginStep,
  loginError,
  ordersCountLabel,
  repeatHref,
} from "@/lib/account";
import { formatPrice } from "@/lib/format";
import { formatDate, STATUS_LABELS } from "@/lib/order";
import { DELIVERY_LABELS, POSTPROCESS_LABELS } from "@/lib/pricing";

const fieldStyle = { borderColor: "var(--muted)", background: "var(--bg)", color: "var(--fg)" };
const buttonStyle = { background: "var(--accent)", color: "var(--bg)" };

export default function AccountPage() {
  const [account, setAccount] = useState<Account | null | undefined>(undefined); // undefined — ещё не знаем

  useEffect(() => {
    fetch("/api/v1/account")
      .then(async (r) => setAccount(r.ok ? ((await r.json()) as Account) : null))
      .catch(() => setAccount(null));
  }, []);

  if (account === undefined) return <main className="mx-auto max-w-3xl px-4 py-16">Загружаем…</main>;
  if (account === null) return <LoginForm onLoggedIn={setAccount} />;
  return <Orders account={account} onLoggedOut={() => setAccount(null)} />;
}

// --- вход -------------------------------------------------------------------------

function LoginForm({ onLoggedIn }: { onLoggedIn: (a: Account) => void }) {
  const [step, setStep] = useState<LoginStep>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function post(path: string, body: object): Promise<Response> {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const data = (await r.json().catch(() => ({}))) as { detail?: unknown };
      throw new Error(loginError(r.status, data.detail));
    }
    return r;
  }

  async function requestCode(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/api/v1/account/login", { email });
      setStep("code");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post("/api/v1/account/login/confirm", { email, code });
      onLoggedIn((await r.json()) as Account);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-md flex-col gap-6 px-4 py-16">
      <h1 className="text-2xl font-bold leading-tight">Кабинет</h1>
      <p className="text-sm" style={{ color: "var(--muted)" }}>
        История заказов и повтор заказа в один клик. Пароль не нужен: укажите e-mail, который вводили
        при заказе, — пришлём код для входа.
      </p>

      {step === "email" ? (
        <form onSubmit={(e) => void requestCode(e)} noValidate className="flex flex-col gap-4 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
          <label className="flex flex-col gap-1 text-sm">
            <span style={{ color: "var(--muted)" }}>E-mail</span>
            <input
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border px-3 py-2"
              style={fieldStyle}
            />
          </label>
          {error && <p role="alert">{error}</p>}
          <button type="submit" disabled={busy || !email.trim()} className="self-start rounded-md px-5 py-2 font-medium disabled:opacity-50" style={buttonStyle}>
            {busy ? "Отправляем…" : "Получить код"}
          </button>
        </form>
      ) : (
        <form onSubmit={(e) => void confirm(e)} noValidate className="flex flex-col gap-4 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
          <p className="text-sm">
            Письмо с кодом ушло на <b>{email.trim()}</b>. Код действует 15 минут; если письма нет — проверьте «Спам».
          </p>
          <label className="flex flex-col gap-1 text-sm">
            <span style={{ color: "var(--muted)" }}>Код из письма</span>
            <input
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="123456"
              value={code}
              onChange={(e) => setCode(cleanCode(e.target.value))}
              className="w-full rounded-md border px-3 py-2 tracking-widest"
              style={fieldStyle}
            />
          </label>
          {error && <p role="alert">{error}</p>}
          <div className="flex flex-wrap items-center gap-4">
            <button type="submit" disabled={busy || code.length !== 6} className="rounded-md px-5 py-2 font-medium disabled:opacity-50" style={buttonStyle}>
              {busy ? "Проверяем…" : "Войти"}
            </button>
            <button
              type="button"
              className="text-sm underline underline-offset-2"
              onClick={() => {
                setStep("email");
                setCode("");
                setError(null);
              }}
            >
              Другой адрес или новый код
            </button>
          </div>
        </form>
      )}
    </main>
  );
}

// --- история заказов ----------------------------------------------------------------

function Orders({ account, onLoggedOut }: { account: Account; onLoggedOut: () => void }) {
  const [orders, setOrders] = useState<AccountOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/account/orders")
      .then(async (r) => {
        if (!r.ok) throw new Error(`Ошибка ${r.status}.`);
        setOrders(((await r.json()) as { orders: AccountOrder[] }).orders);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  async function logout() {
    await fetch("/api/v1/account/logout", { method: "POST" }).catch(() => {});
    onLoggedOut();
  }

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-16">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-bold leading-tight">Мои заказы</h1>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          {account.email} ·{" "}
          <button type="button" onClick={() => void logout()} className="underline underline-offset-2">
            Выйти
          </button>
        </p>
      </div>

      {error && <p role="alert">{error}</p>}
      {orders === null && !error && <p>Загружаем…</p>}

      {orders && orders.length === 0 && (
        <div className="flex flex-col gap-3 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
          <p>Заказов с адресом {account.email} пока нет.</p>
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            Если заказ оформляли без e-mail — он есть по ссылке со страницы заказа. Новые заказы, оформленные
            после входа, попадут сюда сами.
          </p>
          <Link href="/upload" className="self-start rounded-md px-5 py-2 font-medium" style={buttonStyle}>
            Загрузить модель
          </Link>
        </div>
      )}

      {orders && orders.length > 0 && (
        <>
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            {ordersCountLabel(orders.length)}. «Повторить» открывает модель с теми же параметрами — цена
            считается заново по текущему прайсу.
          </p>
          <ul className="flex flex-col gap-4">
            {orders.map((o) => (
              <li key={o.id} className="flex flex-col gap-3 rounded-lg border p-5" style={{ borderColor: "var(--muted)" }} data-testid="order">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <Link href={`/order/${o.token}`} className="text-lg font-semibold underline-offset-2 hover:underline">
                    {o.number}
                  </Link>
                  <span className="text-sm" style={{ color: "var(--muted)" }}>
                    {formatDate(o.created_at)}
                  </span>
                </div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                  <dt style={{ color: "var(--muted)" }}>Модель</dt>
                  <dd className="truncate">{o.original_name ?? o.upload_id}</dd>
                  <dt style={{ color: "var(--muted)" }}>Параметры</dt>
                  <dd>
                    {o.material}
                    {o.supports ? ", с поддержками" : ""}, {o.qty} шт,{" "}
                    {(POSTPROCESS_LABELS[o.postprocess] ?? o.postprocess).toLowerCase()},{" "}
                    {(DELIVERY_LABELS[o.delivery] ?? o.delivery).toLowerCase()}
                  </dd>
                  <dt style={{ color: "var(--muted)" }}>Статус</dt>
                  <dd>{STATUS_LABELS[o.status] ?? o.status}</dd>
                </dl>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-xl font-bold">{formatPrice(o.total)}</span>
                  {o.can_repeat ? (
                    <Link href={repeatHref(o)} className="rounded-md px-4 py-1.5 font-medium" style={buttonStyle}>
                      Повторить
                    </Link>
                  ) : (
                    <span className="text-sm" style={{ color: "var(--muted)" }} title="Файлы старых заказов удаляются по политике персональных данных">
                      Файл модели уже удалён —{" "}
                      <Link href="/upload" className="underline underline-offset-2">
                        загрузите заново
                      </Link>
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
