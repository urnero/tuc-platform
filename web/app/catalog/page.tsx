/**
 * Каталог готовых моделей (B20, дизайн B43): фильтр по категории и материалу, карточки с превью
 * (PNG рисует сервер), габаритами, материалом и кнопкой «Заказать» — components/CatalogBrowser.tsx. Данные — catalog/catalog.yaml через API,
 * страница обновляется раз в 10 минут (ISR); без API показываем «каталог недоступен».
 */

import type { Metadata } from "next";
import Link from "next/link";
import CatalogBrowser from "@/components/CatalogBrowser";
import { groupByCategory, loadCatalog } from "@/lib/catalog";

export const metadata: Metadata = {
  title: "Каталог готовых моделей — BroPrint",
  description: "Готовые модели для 3D-печати: выберите, укажите материал и количество — цена сразу.",
  alternates: { canonical: "/catalog" },
};

export default async function CatalogPage() {
  const catalog = await loadCatalog();
  const groups = catalog ? groupByCategory(catalog) : [];

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 pb-20 pt-10">
      <section className="flex flex-col gap-3">
        <h1 className="text-3xl font-bold">Каталог готовых моделей</h1>
        <p className="max-w-prose" style={{ color: "var(--ink-muted)" }}>
          Нажмите «Заказать» — модель откроется в расчёте: материал, количество, цена сразу. Есть своя модель?{" "}
          <Link href="/upload" className="underline-offset-2 hover:underline" style={{ color: "var(--filament-text)" }}>
            Загрузите её
          </Link>
          .
        </p>
      </section>

      {!catalog && (
        <p role="alert" className="card">
          Каталог временно недоступен. Попробуйте обновить страницу чуть позже или{" "}
          <Link href="/upload" style={{ color: "var(--filament-text)" }}>
            загрузите свою модель
          </Link>
          .
        </p>
      )}
      {catalog && groups.length === 0 && (
        <p className="card">
          В каталоге пока пусто — скоро добавим первые модели.
        </p>
      )}

      {groups.length > 0 && catalog && <CatalogBrowser catalog={catalog} />}
    </main>
  );
}
