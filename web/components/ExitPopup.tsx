"use client";

/**
 * Выходной попап (B52): «Оставьте телефон — посчитаем вручную».
 * Для тех, кто смотрит модели (загрузка, каталог, редакторы), но уходит, не оформив заказ.
 * Когда показывать — правила и сроки в lib/leads.ts (exitPopupAllowed, isDesktopExit, isPhoneReturn).
 * Заявка → POST /api/v1/leads/callback → таблица leads (/admin/leads), Telegram и/или письмо.
 * Подключён один раз в app/layout.tsx.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Field } from "@/components/ui";
import { caughtErrorText, responseErrorText } from "@/lib/errors";
import {
  type CallbackForm,
  EXIT_STORAGE_KEY,
  callbackRequest,
  exitMemory,
  exitPopupAllowed,
  isDesktopExit,
  isPhoneReturn,
  parseExitMemory,
  validateCallback,
} from "@/lib/leads";
import { type LeadResponse, leadSentMessage, studioContacts } from "@/lib/materials";
import { maskPhone } from "@/lib/order";

const SESSION_START = "tuc:session-start";
const SESSION_SHOWN = "tuc:exit-shown";

// Хранилище может быть недоступно (приватный режим, запрет cookies) — тогда попап просто не мешает.
function read(store: "local" | "session", key: string): string | null {
  try {
    return (store === "local" ? window.localStorage : window.sessionStorage).getItem(key);
  } catch {
    return null;
  }
}
function write(store: "local" | "session", key: string, value: string): void {
  try {
    (store === "local" ? window.localStorage : window.sessionStorage).setItem(key, value);
  } catch {
    /* не запомнили — не страшно */
  }
}

export default function ExitPopup() {
  const path = usePathname() || "/";
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<CallbackForm>({ name: "", phone: "" });
  const [phoneError, setPhoneError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<LeadResponse | null>(null);
  const phoneRef = useRef<HTMLDivElement>(null);

  // Можно ли показать прямо сейчас — всё читаем из хранилища в момент сигнала.
  const tryOpen = useCallback(() => {
    const now = Date.now();
    const start = Number(read("session", SESSION_START)) || now;
    const allowed = exitPopupAllowed({
      path,
      memory: parseExitMemory(read("local", EXIT_STORAGE_KEY)),
      shownThisSession: read("session", SESSION_SHOWN) === "1",
      engagedMs: now - start,
      now,
    });
    if (!allowed) return;
    write("session", SESSION_SHOWN, "1");
    setOpen(true);
  }, [path]);

  useEffect(() => {
    if (!read("session", SESSION_START)) write("session", SESSION_START, String(Date.now()));
    let hiddenAt: number | null = null;
    const onMouseOut = (e: MouseEvent) => {
      if (isDesktopExit(e)) tryOpen();
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        hiddenAt = Date.now();
        return;
      }
      // Только на сенсорных экранах: на компьютере смена вкладки — не уход, там есть mouseout.
      const touch = window.matchMedia("(pointer: coarse)").matches;
      if (touch && isPhoneReturn(hiddenAt, Date.now())) tryOpen();
      hiddenAt = null;
    };
    document.addEventListener("mouseout", onMouseOut);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("mouseout", onMouseOut);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [tryOpen]);

  const close = useCallback(() => {
    setOpen(false);
    if (!sent) write("local", EXIT_STORAGE_KEY, exitMemory(Date.now(), false));
  }, [sent]);

  useEffect(() => {
    if (!open) return;
    phoneRef.current?.querySelector("input")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const found = validateCallback(form);
    setPhoneError(found.phone);
    if (found.phone) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/v1/leads/callback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(callbackRequest(form, path)),
      });
      if (!r.ok) throw new Error(await responseErrorText(r));
      setSent((await r.json()) as LeadResponse);
      write("local", EXIT_STORAGE_KEY, exitMemory(Date.now(), true));
    } catch (err) {
      setError(caughtErrorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  const msg = sent ? leadSentMessage(sent, form.phone) : null;
  const contacts = msg?.showContacts ? studioContacts() : [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center"
      style={{ background: "color-mix(in srgb, var(--graphite) 55%, transparent)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
      data-testid="exit-popup"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="exit-popup-title"
        className="card relative flex w-full max-w-md flex-col gap-4"
        style={{ background: "var(--surface-raised)" }}
      >
        <button
          type="button"
          onClick={close}
          aria-label="Закрыть"
          className="absolute right-2 top-2 flex h-11 w-11 items-center justify-center text-xl"
          style={{ color: "var(--ink-muted)" }}
        >
          ✕
        </button>
        {msg ? (
          <div role="status" className="flex flex-col gap-2 pr-8" data-testid="exit-popup-sent">
            <p id="exit-popup-title" className="text-lg font-semibold">
              {msg.title}
            </p>
            <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Позвоним на {form.phone}, спросим про задачу и назовём цену и срок.
              {msg.showContacts && " Ответим в рабочее время. Если срочно — свяжитесь с нами сами:"}
            </p>
            {contacts.length > 0 && (
              <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                {contacts.map((c) => (
                  <li key={c.href}>
                    <a href={c.href} className="underline">
                      {c.label}
                    </a>
                  </li>
                ))}
              </ul>
            )}
            <button type="button" onClick={close} className="btn btn-secondary self-start">
              Хорошо
            </button>
          </div>
        ) : (
          <form onSubmit={submit} noValidate className="flex flex-col gap-4">
            <div className="flex flex-col gap-2 pr-8">
              <p id="exit-popup-title" className="text-lg font-semibold">
                Не получилось посчитать? Посчитаем вручную
              </p>
              <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
                Оставьте телефон — мастер перезвонит, спросит про задачу и назовёт цену и срок.
                Без оплаты и обязательств.
              </p>
            </div>
            <div ref={phoneRef}>
              <Field
                id="exit-phone"
                label="Телефон"
                type="tel"
                inputMode="tel"
                placeholder="+7 999 123-45-67"
                autoComplete="tel"
                value={form.phone}
                error={phoneError}
                onChange={(e) => {
                  setForm((f) => ({ ...f, phone: maskPhone(e.target.value) }));
                  setPhoneError(undefined);
                }}
              />
            </div>
            <Field
              id="exit-name"
              label="Имя (необязательно)"
              autoComplete="name"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            {error && (
              <p role="alert" className="text-sm" style={{ color: "var(--danger)" }}>
                {error}
              </p>
            )}
            <button type="submit" disabled={busy} className="btn btn-primary disabled:opacity-50">
              {busy ? "Отправляем…" : "Перезвоните мне"}
            </button>
            <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
              Нет файла модели?{" "}
              <Link href="/request" className="underline" onClick={close}>
                Пришлите фото или описание
              </Link>
              . Нажимая кнопку, вы соглашаетесь с{" "}
              <Link href="/policy" className="underline" onClick={close}>
                политикой обработки данных
              </Link>
              .
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
