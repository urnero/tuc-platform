/**
 * /request (B52): заявка без модели — «нет STL? пришлите фото или описание».
 * Форма — components/BriefForm.tsx, правила — lib/leads.ts, API — api/app/leads.py.
 */

import type { Metadata } from "next";
import Link from "next/link";
import BriefForm from "@/components/BriefForm";

export const metadata: Metadata = {
  title: "Нет файла модели? Пришлите фото — BroPrint",
  description:
    "Нет STL? Опишите деталь или пришлите фото — мастерская подберёт или смоделирует, назовёт цену и срок.",
  alternates: { canonical: "/request" },
};

export default function RequestPage() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-16">
      <p className="text-xs uppercase tracking-widest" style={{ color: "var(--filament-text)" }}>
        BroPrint · заявка без модели
      </p>
      <h1 className="text-3xl font-bold leading-tight">Нет файла? Пришлите фото или описание</h1>
      <p className="max-w-prose" style={{ color: "var(--ink-muted)" }}>
        Сломалась деталь, нужна копия или есть идея без 3D-модели — опишите задачу. Мастер посмотрит,
        найдёт готовую модель или нарисует свою и позвонит с ценой и сроком. Файл есть?{" "}
        <Link href="/upload" className="underline">
          Загрузите его
        </Link>{" "}
        — цена посчитается сразу.
      </p>
      <BriefForm />
    </main>
  );
}
