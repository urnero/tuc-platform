/**
 * Список параметрических редакторов (B21): карточка на редактор — название, описание, какие
 * параметры можно менять, материал по умолчанию. Данные — editors/<slug>/editor.yaml через API,
 * страница обновляется раз в 10 минут (ISR); без API показываем «редакторы недоступны».
 */

import type { Metadata } from "next";
import Link from "next/link";
import { type Editor, loadEditors } from "@/lib/editors";

export const metadata: Metadata = {
  title: "Редакторы деталей — 3D-печать по вашим размерам — ТУЦ",
  description:
    "Задайте размеры в форме — модель построится сразу, дальше расчёт печати, цена и заказ. Без CAD и без своей модели.",
};

const CARD_BORDER = { borderColor: "color-mix(in srgb, var(--muted) 35%, transparent)" };

function EditorCard({ editor }: { editor: Editor }) {
  const labels = editor.params.map((p) => p.label.toLowerCase());
  return (
    <li className="flex flex-col gap-3 rounded-lg border p-5" style={CARD_BORDER}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">
          <Link href={`/editors/${editor.slug}`} className="underline-offset-2 hover:underline">
            {editor.title}
          </Link>
        </h2>
        <span className="text-xs uppercase tracking-wider" style={{ color: "var(--accent)" }}>
          {editor.material}
        </span>
      </div>
      {editor.text && (
        <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
          {editor.text}
        </p>
      )}
      <p className="text-sm">
        <span style={{ color: "var(--muted)" }}>Можно задать: </span>
        {labels.join(", ")}.
      </p>
      <div className="mt-auto pt-1">
        <Link
          href={`/editors/${editor.slug}`}
          className="inline-block rounded-md px-4 py-2 text-sm font-medium"
          style={{ background: "var(--accent)", color: "var(--bg, #fff)" }}
        >
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
        <p className="max-w-prose" style={{ color: "var(--muted)" }}>
          Нет своей 3D-модели? Выберите деталь, впишите размеры — модель построится на сервере, вы увидите её в
          3D и сразу перейдёте к расчёту и заказу. Готовые модели без настройки — в{" "}
          <Link href="/catalog" className="underline-offset-2 hover:underline" style={{ color: "var(--accent)" }}>
            каталоге
          </Link>
          , своя модель —{" "}
          <Link href="/upload" className="underline-offset-2 hover:underline" style={{ color: "var(--accent)" }}>
            в загрузке
          </Link>
          .
        </p>
      </section>

      {!editors && (
        <p role="alert" className="rounded-lg border p-6" style={CARD_BORDER}>
          Редакторы временно недоступны. Попробуйте обновить страницу чуть позже или{" "}
          <Link href="/upload" style={{ color: "var(--accent)" }}>
            загрузите свою модель
          </Link>
          .
        </p>
      )}
      {editors && editors.length === 0 && (
        <p className="rounded-lg border p-6" style={CARD_BORDER}>
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
