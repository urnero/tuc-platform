"use client";

/**
 * 3D-просмотр модели каталога (B20): тот же ModelViewer, что на странице загрузки,
 * только файл берётся из /api/v1/catalog/<slug>/file. Three.js живёт в браузере,
 * поэтому подключаем через next/dynamic без SSR — а это можно только из клиентского компонента.
 */

import dynamic from "next/dynamic";

const ModelViewer = dynamic(() => import("@/components/ModelViewer"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[420px] items-center justify-center rounded-lg border" style={{ borderColor: "var(--muted)" }}>
      Загружаем 3D-просмотр…
    </div>
  ),
});

export default function CatalogViewer({ url, ext }: { url: string; ext: "stl" | "3mf" }) {
  return <ModelViewer url={url} ext={ext} />;
}
