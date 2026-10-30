"use client";

/**
 * Галерея модели каталога (B43): вкладки «Фото» (превью PNG от сервера, грузится сразу)
 * и «3D» (вращаемый просмотр). Three.js тяжёлый, поэтому 3D подгружается только по клику —
 * на телефоне первый экран открывается быстрее. Новые снимки — в `images` (пока сервер
 * отдаёт одно превью; фото готовых изделий добавятся вместе с B41/п. 10 «Нужно от владельца»).
 */

import Image from "next/image";
import { useState } from "react";
import CatalogViewer from "@/components/CatalogViewer";

type Props = {
  title: string;
  images: string[];
  fileUrl: string;
  ext: "stl" | "3mf";
};

export default function ModelGallery({ title, images, fileUrl, ext }: Props) {
  // Вкладка: номер снимка или "3d".
  const [view, setView] = useState<number | "3d">(0);

  return (
    <div className="flex flex-col gap-3">
      {view === "3d" ? (
        <CatalogViewer url={fileUrl} ext={ext} />
      ) : (
        <div className="relative aspect-[4/3] w-full overflow-hidden rounded-[var(--radius-md)]" style={{ background: "var(--sand)" }}>
          <Image
            src={images[view] ?? images[0]}
            alt={`${title} — превью модели`}
            fill
            unoptimized
            priority
            sizes="(min-width: 1024px) 560px, 100vw"
            className="object-contain p-6"
          />
        </div>
      )}
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Как показать модель">
        {images.map((src, i) => (
          <button
            key={src}
            type="button"
            role="tab"
            aria-selected={view === i}
            onClick={() => setView(i)}
            className="relative h-16 w-20 overflow-hidden rounded-[var(--radius-sm)] border-2"
            style={{ background: "var(--sand)", borderColor: view === i ? "var(--filament)" : "var(--line)" }}
          >
            <Image src={src} alt={`Снимок ${i + 1}`} fill unoptimized sizes="80px" className="object-contain p-1" />
          </button>
        ))}
        <button
          type="button"
          role="tab"
          aria-selected={view === "3d"}
          onClick={() => setView("3d")}
          className="flex h-16 w-20 flex-col items-center justify-center rounded-[var(--radius-sm)] border-2 text-sm font-semibold"
          style={{ borderColor: view === "3d" ? "var(--filament)" : "var(--line)" }}
        >
          <span aria-hidden className="text-lg leading-none">⟳</span>
          3D
        </button>
      </div>
      <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
        {view === "3d" ? "Крутите модель пальцем или мышью, колесо — приблизить." : "Нажмите «3D», чтобы покрутить модель со всех сторон."}
      </p>
    </div>
  );
}
