/**
 * Страница модели каталога (B20, дизайн B43): галерея (фото + 3D), описание, габариты, лицензия,
 * «Заказать» и «Ещё в этой категории».
 * Серверный компонент: данные с API, метатеги для поиска; просмотр и кнопка — клиентские.
 */

import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import CatalogOrderButton from "@/components/CatalogOrderButton";
import ModelGallery from "@/components/ModelGallery";
import { type CatalogModel, dimsText, loadCatalog, loadCatalogModel } from "@/lib/catalog";
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

  // Соседи по категории — до трёх, чтобы было куда пойти дальше, если эта модель не подошла.
  const catalog = await loadCatalog();
  const related: CatalogModel[] = catalog
    ? catalog.models.filter((x) => x.category === model.category && x.slug !== model.slug).slice(0, 3)
    : [];
  const categoryTitle = catalog?.categories.find((c) => c.slug === model.category)?.title;

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 pb-20 pt-8">
      <nav aria-label="Хлебные крошки" className="flex flex-wrap gap-1 text-sm" style={{ color: "var(--ink-muted)" }}>
        <Link href="/catalog" style={{ color: "var(--filament-text)" }}>
          Каталог
        </Link>
        {categoryTitle && (
          <>
            <span aria-hidden>/</span>
            <Link href={`/catalog?cat=${model.category}`} style={{ color: "var(--filament-text)" }}>
              {categoryTitle}
            </Link>
          </>
        )}
      </nav>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-start">
        <ModelGallery title={model.title} images={[model.preview_url]} fileUrl={model.file_url} ext={model.ext} />

        <section className="card flex flex-col gap-4 lg:sticky lg:top-24">
          <div className="flex flex-col gap-2">
            <span className="badge badge-neutral w-fit">{model.material}</span>
            <h1 className="text-2xl font-bold leading-tight">{model.title}</h1>
          </div>
          {model.text && <p className="leading-relaxed">{model.text}</p>}
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt style={{ color: "var(--ink-muted)" }}>Габариты</dt>
            <dd>{dims ?? "уточняются"}</dd>
            {m && (
              <>
                <dt style={{ color: "var(--ink-muted)" }}>Объём</dt>
                <dd>{m.volume_cm3.toFixed(1).replace(".", ",")} см³</dd>
              </>
            )}
            <dt style={{ color: "var(--ink-muted)" }}>Материал</dt>
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
          <div className="flex flex-col gap-2 pt-2">
            <CatalogOrderButton slug={model.slug} size="lg" />
            <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Дальше — материал, количество и цена сразу. Оплата после расчёта.
            </span>
          </div>
        </section>
      </div>

      {related.length > 0 && (
        <section className="flex flex-col gap-4 pt-6" aria-labelledby="related-heading">
          <h2 id="related-heading" className="text-xl font-bold">
            Ещё в этой категории
          </h2>
          <ul className="grid gap-4 sm:grid-cols-3">
            {related.map((r) => (
              <li key={r.slug}>
                <Link href={`/catalog/${r.slug}`} className="card flex h-full flex-col gap-2 !p-3 hover:border-[var(--steel)]">
                  <span className="relative block aspect-[4/3] overflow-hidden rounded-[var(--radius-sm)]" style={{ background: "var(--sand)" }}>
                    <Image src={r.preview_url} alt="" fill unoptimized sizes="(min-width: 640px) 300px, 100vw" className="object-contain p-3" />
                  </span>
                  <span className="font-semibold">{r.title}</span>
                  <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
                    {dimsText(r) ?? r.material}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
