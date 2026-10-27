/**
 * Список параметрических редакторов (B21, дизайн B43): карточка на редактор — название, описание,
 * параметры с диапазонами, материал по умолчанию. Данные — editors/<slug>/editor.yaml через API,
 * страница обновляется раз в 10 минут (ISR); без API показываем «редакторы недоступны».
 */

import type { Metadata } from "next";
import Link from "next/link";
import { type Editor, loadEditors, rangeHint } from "@/lib/editors";
import { buttonClass } from "@/lib/ui";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  path: "/editors",
  title: "Редакторы деталей — 3D-печать по вашим размерам — BroPrint",
  description:
    "Задайте размеры в форме — модель построится сразу, дальше расчёт печати, цена и заказ. Без CAD и без своей модели.",
});

function EditorCard({ editor }: { editor: Editor }) {
  // Первые четыре параметра с диапазонами — чтобы сразу было видно, что можно задать и в каких пределах.
  const shown = editor.params.slice(0, 4);
  const more = editor.params.length - shown.length;
  return (
    <li className="card flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-lg font-semibold leading-snug">
          <Link href={`/editors/${editor.slug}`} className="underline-offset-2 hover:underline">
            {editor.title}
          </Link>
        </h2>
        <span className="badge badge-neutral shrink-0">{editor.material}</span>
      </div>
      {editor.text && (
        <p className="text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>
          {editor.text}
        </p>
      )}
      <ul className="flex flex-col gap-1 text-sm">
        {shown.map((p) => {
          const hint = p.type === "number" ? rangeHint({ ...p, hint: "" }) : "";
          return (
            <li key={p.name} className="flex justify-between gap-3 border-b pb-1 last:border-0" style={{ borderColor: "var(--line)" }}>
              <span>{p.label}</span>
              {hint && <span style={{ color: "var(--ink-muted)" }}>{hint}</span>}
            </li>
          );
        })}
        {more > 0 && <li style={{ color: "var(--ink-muted)" }}>и ещё {more}</li>}
      </ul>
      <div className="mt-auto pt-1">
        <Link href={`/editors/${editor.slug}`} className={buttonClass("primary", "sm")}>
          Открыть редактор
        </Link>
      </div>
    </li>
  );
}

export default async function EditorsPage() {
  const editors = await loadEditors();

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-10 px-4 pb-20 pt-10">
      <section className="flex flex-col gap-3">
        <h1 className="text-3xl font-bold">Редакторы деталей</h1>
        <p className="max-w-prose" style={{ color: "var(--ink-muted)" }}>
          Нет своей 3D-модели? Выберите деталь, впишите размеры — модель построится на сервере, вы увидите её в
          3D и сразу перейдёте к расчёту и заказу. Готовые модели без настройки — в{" "}
          <Link href="/catalog" className="underline-offset-2 hover:underline" style={{ color: "var(--filament-text)" }}>
            каталоге
          </Link>
          , своя модель —{" "}
          <Link href="/upload" className="underline-offset-2 hover:underline" style={{ color: "var(--filament-text)" }}>
            в загрузке
          </Link>
          .
        </p>
      </section>

      {!editors && (
        <p role="alert" className="card">
          Редакторы временно недоступны. Попробуйте обновить страницу чуть позже или{" "}
          <Link href="/upload" style={{ color: "var(--filament-text)" }}>
            загрузите свою модель
          </Link>
          .
        </p>
      )}
      {editors && editors.length === 0 && (
        <p className="card">
          Редакторов пока нет — скоро добавим первые.
        </p>
      )}

      {editors && editors.length > 0 && (
        <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {editors.map((e) => (
            <EditorCard key={e.slug} editor={e} />
          ))}
        </ul>
      )}
    </main>
  );
}
