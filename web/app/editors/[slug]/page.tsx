/**
 * Страница редактора (B21): форма параметров → сборка модели на сервере (OpenSCAD) →
 * 3D-просмотр → «Заказать». Серверный компонент отдаёт схему и метатеги; сама форма,
 * опрос сборки и просмотр — в клиентском EditorWorkbench.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import EditorWorkbench from "@/components/EditorWorkbench";
import { loadEditor } from "@/lib/editors";

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const editor = await loadEditor(slug);
  if (!editor) return { title: "Редактор не найден — ТУЦ" };
  return {
    title: `${editor.title} по вашим размерам — 3D-печать — ТУЦ`,
    description: editor.text || `Задайте размеры «${editor.title}» — модель построится сразу, дальше цена и заказ.`,
  };
}

export default async function EditorPage({ params }: Params) {
  const { slug } = await params;
  const editor = await loadEditor(slug);
  if (!editor) notFound();

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-16">
      <Link href="/editors" className="text-sm" style={{ color: "var(--accent)" }}>
        ← Все редакторы
      </Link>
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold leading-tight">{editor.title}</h1>
        {editor.text && (
          <p className="max-w-prose leading-relaxed" style={{ color: "var(--muted)" }}>
            {editor.text}
          </p>
        )}
      </div>
      <EditorWorkbench editor={editor} />
    </main>
  );
}
