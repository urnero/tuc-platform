"use client";

/**
 * Заявка «цена по запросу» (B44) — для смол (SLA): цену называет мастерская, оплаты на сайте нет.
 * Показывается в блоке расчёта вместо кнопки «Рассчитать», когда выбрана смола.
 * POST /api/v1/uploads/{id}/request → таблица leads (/admin/leads) + Telegram и/или письмо владельцу.
 * Если ни один канал не настроен — клиенту честный текст и контакты студии (leadSentMessage).
 */

import { useState } from "react";
import { Field } from "@/components/ui";
import { caughtErrorText, responseErrorText } from "@/lib/errors";
import {
  EMPTY_LEAD,
  type LeadForm as Form,
  type LeadResponse,
  leadRequest,
  leadSentMessage,
  studioContacts,
  validateLead,
} from "@/lib/materials";
import { maskPhone } from "@/lib/order";

type Props = {
  uploadId: string;
  material: string;
  materialName: string;
  qty: number;
};

export default function LeadForm({
  uploadId,
  material,
  materialName,
  qty,
}: Props) {
  const [form, setForm] = useState<Form>(EMPTY_LEAD);
  const [errors, setErrors] = useState<Partial<Record<keyof Form, string>>>({});
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<LeadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof Form) => (e: { target: { value: string } }) => {
    const value = k === "phone" ? maskPhone(e.target.value) : e.target.value;
    setForm((f) => ({ ...f, [k]: value }));
    if (errors[k]) setErrors((er) => ({ ...er, [k]: undefined }));
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const found = validateLead(form);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/v1/uploads/${uploadId}/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(leadRequest(form, material, qty)),
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
      <div
        className="card flex flex-col gap-2"
        role="status"
        data-testid="lead-sent"
      >
        <p className="font-semibold">{msg.title}</p>
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
          {msg.text}
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
    <form
      onSubmit={submit}
      noValidate
      className="flex flex-col gap-4"
      data-testid="lead-form"
    >
      <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
        {materialName}: цену смолы считаем вручную — она зависит от ориентации,
        поддержек и постобработки. Оставьте контакт — назовём цену и срок,
        оплата после подтверждения.
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field
          id="lead-name"
          label="Имя"
          value={form.name}
          onChange={set("name")}
          error={errors.name}
          autoComplete="name"
        />
        <Field
          id="lead-phone"
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
          id="lead-email"
          label="E-mail (необязательно)"
          type="email"
          value={form.email}
          onChange={set("email")}
          error={errors.email}
          autoComplete="email"
        />
        <Field
          id="lead-comment"
          label="Комментарий (необязательно)"
          multiline
          rows={2}
          placeholder="Цвет, срок, для чего деталь"
          value={form.comment}
          onChange={set("comment")}
        />
      </div>
      {error && (
        <p role="alert" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy}
        className="btn btn-primary self-start disabled:opacity-50"
      >
        {busy ? "Отправляем…" : "Узнать цену"}
      </button>
    </form>
  );
}
