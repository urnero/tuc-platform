/**
 * Кирпичики для текстовых страниц (B13): оферта, политика, «О студии», контакты.
 * Это серверные компоненты без состояния — просто разметка и отступы.
 */

import type { ReactNode } from "react";
import { missingRequisites } from "@/lib/company";

/** Страница с заголовком, подзаголовком и колонкой текста. */
export function Doc({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-12">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold leading-tight">{title}</h1>
        {subtitle && (
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            {subtitle}
          </p>
        )}
      </header>
      {children}
    </main>
  );
}

/** Раздел документа: нумерованный заголовок и абзацы. */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xl font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export function P({ children }: { children: ReactNode }) {
  return <p className="max-w-prose leading-relaxed">{children}</p>;
}

/** Список пунктов внутри раздела. */
export function Items({ items }: { items: ReactNode[] }) {
  return (
    <ul className="flex max-w-prose list-disc flex-col gap-1 pl-5 leading-relaxed">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

/** Таблица «название — значение» для реквизитов и контактов. */
export function Facts({ rows }: { rows: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid max-w-prose grid-cols-[max-content_1fr] gap-x-6 gap-y-2">
      {rows.map((r) => (
        <div key={r.label} className="contents">
          <dt style={{ color: "var(--muted)" }}>{r.label}</dt>
          <dd>{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Предупреждение, если владелец ещё не вписал обязательные реквизиты в web/lib/company.ts.
 * Исчезает само, как только поля заполнены.
 */
export function MissingRequisitesNote() {
  const missing = missingRequisites();
  if (missing.length === 0) return null;
  return (
    <p
      className="max-w-prose rounded-md border px-4 py-3 text-sm"
      style={{ borderColor: "var(--accent)", color: "var(--muted)" }}
      data-testid="missing-requisites"
    >
      Реквизиты исполнителя ({missing.join(", ")}) будут опубликованы до начала приёма оплат. Пока документ —
      предварительная редакция.
    </p>
  );
}
