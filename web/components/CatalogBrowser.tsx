"use client";

/**
 * Каталог с фильтром (B43): кнопки-«чипы» по категории и материалу, карточки с превью.
 * Без фильтра модели идут разделами по категориям (как в catalog.yaml), с фильтром —
 * одной сеткой. Фильтр пишется в адрес (?cat=…&mat=…), чтобы ссылкой можно было поделиться;
 * сервер отдаёт страницу без фильтра (её видят поисковики), фильтр применяется в браузере.
 */

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import CatalogOrderButton from "@/components/CatalogOrderButton";
import {
  type Catalog,
  type CatalogFilter,
  type CatalogModel,
  dimsText,
  filterModels,
  filterQuery,
  groupByCategory,
  materialsOf,
  modelsWord,
  NO_FILTER,
  parseFilter,
} from "@/lib/catalog";

export default function CatalogBrowser({ catalog }: { catalog: Catalog }) {
  const [filter, setFilter] = useState<CatalogFilter>(NO_FILTER);

  // Фильтр из адреса — после загрузки страницы (на сервере адреса с ?cat не знаем).
  useEffect(() => {
    setFilter(parseFilter(window.location.search, catalog));
  }, [catalog]);

  function choose(next: CatalogFilter) {
    setFilter(next);
    window.history.replaceState(null, "", `${window.location.pathname}${filterQuery(next)}`);
  }

  const groups = groupByCategory(catalog);
  const materials = materialsOf(catalog.models);
  const active = filter.category !== "" || filter.material !== "";
  const found = filterModels(catalog.models, filter).filter((m) => groups.some((g) => g.category.slug === m.category));

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3" role="group" aria-label="Фильтр каталога">
        {groups.length > 1 && (
          <ChipRow label="Категория">
            <Chip on={filter.category === ""} onClick={() => choose({ ...filter, category: "" })}>
              Все
            </Chip>
            {groups.map(({ category, models }) => (
              <Chip key={category.slug} on={filter.category === category.slug} onClick={() => choose({ ...filter, category: category.slug })}>
                {category.title} <span style={{ color: "var(--ink-muted)" }}>{models.length}</span>
              </Chip>
            ))}
          </ChipRow>
        )}
        {materials.length > 1 && (
          <ChipRow label="Материал">
            <Chip on={filter.material === ""} onClick={() => choose({ ...filter, material: "" })}>
              Любой
            </Chip>
            {materials.map((m) => (
              <Chip key={m} on={filter.material === m} onClick={() => choose({ ...filter, material: m })}>
                {m}
              </Chip>
            ))}
          </ChipRow>
        )}
        {active && (
          <p className="flex flex-wrap items-center gap-3 text-sm" aria-live="polite">
            <span>
              Нашли {found.length} {modelsWord(found.length)}
            </span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => choose(NO_FILTER)}>
              Сбросить фильтр
            </button>
          </p>
        )}
      </div>

      {active ? (
        found.length > 0 ? (
          <ModelGrid models={found} />
        ) : (
          <div className="card flex flex-col items-start gap-3">
            <p>Под такой фильтр моделей пока нет. Материал можно поменять при расчёте — подойдёт любая модель.</p>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => choose(NO_FILTER)}>
              Показать все модели
            </button>
          </div>
        )
      ) : (
        groups.map(({ category, models }) => (
          <section key={category.slug} id={category.slug} className="flex scroll-mt-24 flex-col gap-4">
            <div className="flex flex-col gap-1">
              <h2 className="text-2xl font-bold">{category.title}</h2>
              {category.text && (
                <p className="max-w-prose" style={{ color: "var(--ink-muted)" }}>
                  {category.text}
                </p>
              )}
            </div>
            <ModelGrid models={models} />
          </section>
        ))
      )}
    </div>
  );
}

function ChipRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
      <span className="text-sm font-semibold sm:w-24 sm:shrink-0">{label}</span>
      {/* На телефоне — одна строка с прокруткой вбок, чтобы фильтр не съедал первый экран. */}
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0">
        {children}
      </div>
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className="inline-flex min-h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 text-sm transition-colors"
      style={
        on
          ? { background: "var(--filament)", borderColor: "var(--filament)", color: "var(--on-filament)", fontWeight: 600 }
          : { borderColor: "var(--steel)", color: "var(--ink)" }
      }
    >
      {children}
    </button>
  );
}

function ModelGrid({ models }: { models: CatalogModel[] }) {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {models.map((m) => (
        <ModelCard key={m.slug} model={m} />
      ))}
    </ul>
  );
}

function ModelCard({ model }: { model: CatalogModel }) {
  const dims = dimsText(model);
  return (
    <li className="card flex flex-col gap-0 overflow-hidden !p-0">
      <Link href={`/catalog/${model.slug}`} className="relative block aspect-[4/3]" style={{ background: "var(--sand)" }} tabIndex={-1} aria-hidden>
        <Image
          src={model.preview_url}
          alt=""
          fill
          unoptimized
          sizes="(min-width: 1024px) 320px, (min-width: 640px) 50vw, 100vw"
          className="object-contain p-4 transition-transform duration-200 hover:scale-105"
        />
        <span className="badge badge-neutral absolute left-3 top-3">{model.material}</span>
      </Link>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <h3 className="font-semibold leading-snug">
          <Link href={`/catalog/${model.slug}`} className="underline-offset-2 hover:underline">
            {model.title}
          </Link>
        </h3>
        {model.text && (
          <p className="line-clamp-3 text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>
            {model.text}
          </p>
        )}
        <div className="mt-auto flex items-center justify-between gap-3 pt-2">
          <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
            {dims ?? "Габариты уточняются"}
          </span>
          <CatalogOrderButton slug={model.slug} />
        </div>
      </div>
    </li>
  );
}
