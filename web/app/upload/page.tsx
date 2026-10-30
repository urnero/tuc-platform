/**
 * Страница загрузки модели (B02): /upload.
 * Сама зона загрузки — components/UploadDropzone.tsx (та же, что на главной).
 */

import type { Metadata } from "next";
import UploadDropzone from "@/components/UploadDropzone";
import { MAX_UPLOAD_MB } from "@/lib/mesh";

export const metadata: Metadata = {
  title: "Загрузить модель — BroPrint",
  description: "Загрузите STL или 3MF — проверим сетку, покажем габариты и посчитаем цену печати.",
  alternates: { canonical: "/upload" },
};

export default function UploadPage() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-16">
      <p className="text-xs uppercase tracking-widest" style={{ color: "var(--filament-text)" }}>
        BroPrint · загрузка модели
      </p>
      <h1 className="text-3xl font-bold leading-tight">Загрузите модель для печати</h1>
      <p className="max-w-prose" style={{ color: "var(--ink-muted)" }}>
        STL или 3MF, до {MAX_UPLOAD_MB} МБ. Мы проверим сетку и покажем габариты.
      </p>
      <UploadDropzone />
    </main>
  );
}
