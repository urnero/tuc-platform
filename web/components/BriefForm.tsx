"use client";

/**
 * Заявка без модели (B52): «нет STL — пришлите фото или описание». Страница /request.
 * POST /api/v1/leads/brief (form-data: поля + фото по желанию) → таблица leads (/admin/leads),
 * Telegram и/или письмо владельцу. Проверки — lib/leads.ts::validateBrief (те же, что на сервере).
 */

import { useState } from "react";
import { Field } from "@/components/ui";
import { caughtErrorText, responseErrorText } from "@/lib/errors";
import {
  type BriefForm as Form,
  EMPTY_BRIEF,
  PHOTO_ACCEPT,
  PHOTO_MAX_MB,
  briefFormData,
  validateBrief,
} from "@/lib/leads";
import { type LeadResponse, leadSentMessage, studioContacts } from "@/lib/materials";
import { maskPhone } from "@/lib/order";

type Errors = Partial<Record<keyof Form | "photo", string>>;

export default function BriefForm() {
  const [form, setForm] = useState<Form>(EMPTY_BRIEF);
  const [photo, setPhoto] = useState<File | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<LeadResponse | null>(null);

  const set = (k: keyof Form) => (e: { target: { value: string } }) => {
    const value = k === "phone" ? maskPhone(e.target.value) : e.target.value;
    setForm((f) => ({ ...f, [k]: value }));
    if (errors[k]) setErrors((er) => ({ ...er, [k]: undefined }));
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const found = validateBrief(form, photo);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/v1/leads/brief", {
        method: "POST",
        body: briefFormData(form, photo, "/request"),
      });
      if (!r.ok) throw new Error(await responseErrorText(r));
      setSent((await r.json()) as LeadResponse);
    } catch (err) {
      setError(caughtErrorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    const msg = leadSentMessage(sent, form.phone);
    const contacts = msg.showContacts ? studioContacts() : [];
    return (
      <div className="card flex flex-col gap-2" role="status" data-testid="brief-sent">
        <p className="font-semibold">{msg.title}</p>
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
          {msg.text.replace("Посмотрим модель", "Посмотрим описание")}
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
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="card flex flex-col gap-4" data-testid="brief-form">
      <Field
        id="brief-comment"
        label="Что нужно напечатать"
        multiline
        rows={4}
        placeholder="Например: сломалась ручка кухонного шкафа, нужна такая же, длина 12 см. Или: держатель для телефона на руль велосипеда."
        value={form.comment}
        onChange={set("comment")}
        error={errors.comment}
      />
      <div className="flex flex-col gap-1">
        <label htmlFor="brief-photo" className="text-sm font-medium">
          Фото детали или эскиз (необязательно)
        </label>
        <input
          id="brief-photo"
          type="file"
          accept={PHOTO_ACCEPT}
          aria-describedby="brief-photo-note"
          aria-invalid={errors.photo ? true : undefined}
          className="text-sm"
          onChange={(e) => {
            setPhoto(e.target.files?.[0] ?? null);
            setErrors((er) => ({ ...er, photo: undefined }));
          }}
        />
        <p
          id="brief-photo-note"
          className="text-sm"
          style={{ color: errors.photo ? "var(--danger)" : "var(--ink-muted)" }}
        >
          {errors.photo ?? `JPG, PNG, WEBP или HEIC до ${PHOTO_MAX_MB} МБ. Положите рядом линейку — так проще понять размер.`}
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field id="brief-name" label="Имя" value={form.name} onChange={set("name")} error={errors.name} autoComplete="name" />
        <Field
          id="brief-phone"
          label="Телефон"
          type="tel"
          inputMode="tel"
          placeholder="+7 999 123-45-67"
          value={form.phone}
          onChange={set("phone")}
          error={errors.phone}
          autoComplete="tel"
        />
        <Field
          id="brief-email"
          label="E-mail (необязательно)"
          type="email"
          value={form.email}
          onChange={set("email")}
          error={errors.email}
          autoComplete="email"
        />
        <Field
          id="brief-qty"
          label="Сколько штук"
          type="number"
          inputMode="numeric"
          min={1}
          max={10000}
          value={form.qty}
          onChange={set("qty")}
          error={errors.qty}
        />
      </div>
      {error && (
        <p role="alert" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      <button type="submit" disabled={busy} className="btn btn-primary self-start disabled:opacity-50">
        {busy ? "Отправляем…" : "Отправить заявку"}
      </button>
      <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
        Нажимая кнопку, вы соглашаетесь с{" "}
        <a href="/policy" className="underline">
          политикой обработки данных
        </a>
        . Оплата — только после того, как мы назовём цену и вы согласитесь.
      </p>
    </form>
  );
}
