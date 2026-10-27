/**
 * Каталог готовых моделей (B20): категории → карточки с превью (PNG рисует сервер),
 * габаритами, материалом и кнопкой «Заказать». Данные — catalog/catalog.yaml через API,
 * страница обновляется раз в 10 минут (ISR); без API показываем «каталог недоступен».
 */

import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import CatalogOrderButton from "@/components/CatalogOrderButton";
import { type CatalogModel, dimsText, groupByCategory, loadCatalog } from "@/lib/catalog";

export const metadata: Metadata = {
  title: "Каталог готовых моделей — ТУЦ",
  description: "Готовые модели для 3D-печати: выберите, укажите материал и количество — цена сразу.",
  alternates: { canonical: "/catalog" },
};

const CARD_BORDER = { borderColor: "color-mix(in srgb, var(--muted) 35%, transparent)" };

function ModelCard({ model }: { model: CatalogModel }) {
  const dims = dimsText(model);
  return (
    <li className="flex flex-col overflow-hidden rounded-lg border" style={CARD_BORDER}>
      <Link href={`/catalog/${model.slug}`} className="relative block aspect-[4/3]" style={{ background: "color-mix(in srgb, var(--muted) 12%, transparent)" }}>
        <Image
          src={model.preview_url}
          alt={model.title}
          fill
          unoptimized
          sizes="(min-width: 1024px) 320px, (min-width: 640px) 50vw, 100vw"
          className="object-contain p-4"
        />
      </Link>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-semibold">
            <Link href={`/catalog/${model.slug}`} className="underline-offset-2 hover:underline">
              {model.title}
            </Link>
          </h3>
          <span className="text-xs uppercase tracking-wider" style={{ color: "var(--accent)" }}>
            {model.material}
          </span>
        </div>
        {model.text && (
          <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
            {model.text}
          </p>
        )}
        <div className="mt-auto flex items-center justify-between gap-3 pt-2">
          <span className="text-sm" style={{ color: "var(--muted)" }}>
            {dims ?? "Габариты уточняются"}
          </span>
          <CatalogOrderButton slug={model.slug} />
        </div>
      </div>
    </li>
  );
}

export default async function CatalogPage() {
  const catalog = await loadCatalog();
  const groups = catalog ? groupByCategory(catalog) : [];

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-12 px-4 pb-20 pt-10">
      <section className="flex flex-col gap-3">
        <h1 className="text-3xl font-bold">Каталог готовых моделей</h1>
        <p className="max-w-prose" style={{ color: "var(--muted)" }}>
          Нажмите «Заказать» — модель откроется в расчёте: материал, количество, цена сразу. Есть своя модель?{" "}
          <Link href="/upload" className="underline-offset-2 hover:underline" style={{ color: "var(--accent)" }}>
            Загрузите её
          </Link>
          .
        </p>
        {groups.length > 1 && (
          <nav className="flex flex-wrap gap-2 text-sm" aria-label="Категории">
            {groups.map(({ category }) => (
              <a key={category.slug} href={`#${category.slug}`} className="rounded-full border px-3 py-1 underline-offset-2 hover:underline" style={CARD_BORDER}>
                {category.title} · {category.count}
              </a>
            ))}
          </nav>
        )}
      </section>

      {!catalog && (
        <p role="alert" className="rounded-lg border p-6" style={CARD_BORDER}>
          Каталог временно недоступен. Попробуйте обновить страницу чуть позже или{" "}
          <Link href="/upload" style={{ color: "var(--accent)" }}>
            загрузите свою модель
          </Link>
          .
        </p>
      )}
      {catalog && groups.length === 0 && (
        <p className="rounded-lg border p-6" style={CARD_BORDER}>
          В каталоге пока пусто — скоро добавим первые модели.
        </p>
      )}

      {groups.map(({ category, models }) => (
        <section key={category.slug} id={category.slug} className="flex scroll-mt-24 flex-col gap-5">
          <div className="flex flex-col gap-1">
            <h2 className="text-2xl font-bold">{category.title}</h2>
            {category.text && (
              <p className="max-w-prose" style={{ color: "var(--muted)" }}>
                {category.text}
              </p>
            )}
          </div>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {models.map((m) => (
              <ModelCard key={m.slug} model={m} />
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
