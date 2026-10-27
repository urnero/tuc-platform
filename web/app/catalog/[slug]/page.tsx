/**
 * Страница модели каталога (B20): 3D-просмотр, описание, габариты, лицензия и «Заказать».
 * Серверный компонент: данные с API, метатеги для поиска; просмотр и кнопка — клиентские.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import CatalogOrderButton from "@/components/CatalogOrderButton";
import CatalogViewer from "@/components/CatalogViewer";
import { dimsText, loadCatalogModel } from "@/lib/catalog";
import { warningText } from "@/lib/mesh";
import { metaDescription, pageMetadata } from "@/lib/seo";

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const model = await loadCatalogModel(slug);
  if (!model) return { title: "Модель не найдена — BroPrint", robots: { index: false } };
  // Канонический адрес и карточка с превью модели для мессенджеров (B25).
  return pageMetadata({
    path: `/catalog/${model.slug}`,
    title: `${model.title} — 3D-печать на заказ — BroPrint`,
    description: metaDescription(model.text, `Готовая модель «${model.title}»: выберите материал и количество — цена сразу.`),
    image: model.preview_url,
  });
}

export default async function CatalogModelPage({ params }: Params) {
  const { slug } = await params;
  const model = await loadCatalogModel(slug);
  if (!model) notFound();

  const dims = dimsText(model);
  const m = model.mesh;

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-16">
      <Link href="/catalog" className="text-sm" style={{ color: "var(--filament-text)" }}>
        ← Все модели
      </Link>
      <h1 className="text-2xl font-bold leading-tight">{model.title}</h1>

      <CatalogViewer url={model.file_url} ext={model.ext} />

      <section className="flex flex-col gap-4 rounded-lg border p-6" style={{ borderColor: "var(--ink-muted)" }}>
        {model.text && <p className="leading-relaxed">{model.text}</p>}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <dt style={{ color: "var(--ink-muted)" }}>Габариты</dt>
          <dd>{dims ?? "уточняются"}</dd>
          {m && (
            <>
              <dt style={{ color: "var(--ink-muted)" }}>Объём</dt>
              <dd>{m.volume_cm3.toFixed(1).replace(".", ",")} см³</dd>
            </>
          )}
          <dt style={{ color: "var(--ink-muted)" }}>Материал по умолчанию</dt>
          <dd>{model.material} — можно поменять при расчёте</dd>
          {model.license && (
            <>
              <dt style={{ color: "var(--ink-muted)" }}>Лицензия</dt>
              <dd>{model.license}</dd>
            </>
          )}
        </dl>
        {m && m.warnings.length > 0 && (
          <ul className="flex flex-col gap-1 text-sm">
            {m.warnings.map((w) => (
              <li key={w}>⚠ {warningText(w)}</li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-center gap-4 pt-2">
          <CatalogOrderButton slug={model.slug} size="lg" />
          <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
            Дальше — расчёт печати, цена и оформление заказа.
          </span>
        </div>
      </section>
    </main>
  );
}
