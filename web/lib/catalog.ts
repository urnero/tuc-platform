/**
 * Каталог готовых моделей (B20): типы ответа GET /api/v1/catalog и помощники для страниц
 * /catalog и /catalog/[slug]. Данные приходят из catalog/catalog.yaml через API;
 * страницы кэшируются на 10 минут (ISR) — владелец правит yaml, сайт подхватывает сам.
 */

import { apiInternalUrl } from "./landing";
import { formatDims, type MeshInfo } from "./mesh";

export type CatalogCategory = {
  slug: string;
  title: string;
  text: string;
  /** Сколько моделей в категории (считает API). */
  count: number;
};

export type CatalogModel = {
  slug: string;
  title: string;
  category: string;
  text: string;
  file: string;
  ext: "stl" | "3mf";
  /** Материал, который подставится в калькулятор по умолчанию. */
  material: string;
  license: string;
  preview_url: string;
  file_url: string;
  /** null — файл модели не найден или не читается; карточка показывается без габаритов. */
  mesh: MeshInfo | null;
};

export type Catalog = { categories: CatalogCategory[]; models: CatalogModel[] };

/** Весь каталог с сервера Next. API недоступен (сборка образа) → null, страница не падает. */
export async function loadCatalog(): Promise<Catalog | null> {
  try {
    const r = await fetch(`${apiInternalUrl()}/api/v1/catalog`, { next: { revalidate: 600 } });
    if (!r.ok) return null;
    return (await r.json()) as Catalog;
  } catch {
    return null;
  }
}

/** Одна модель; нет такой — null. Ошибка сети тоже null: страница покажет «не найдена». */
export async function loadCatalogModel(slug: string): Promise<CatalogModel | null> {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) return null;
  try {
    const r = await fetch(`${apiInternalUrl()}/api/v1/catalog/${slug}`, { next: { revalidate: 600 } });
    if (!r.ok) return null;
    return (await r.json()) as CatalogModel;
  } catch {
    return null;
  }
}

export type CategoryGroup = { category: CatalogCategory; models: CatalogModel[] };

/**
 * Модели по категориям в порядке из yaml. Пустые категории не показываем;
 * модели с неизвестной категорией (не должно быть — API их не пропустит) — тоже.
 */
export function groupByCategory(catalog: Catalog): CategoryGroup[] {
  return catalog.categories
    .map((category) => ({ category, models: catalog.models.filter((m) => m.category === category.slug) }))
    .filter((g) => g.models.length > 0);
}

/** Подпись габаритов для карточки: «90 × 90 × 7 мм»; без сетки — null. */
export function dimsText(model: CatalogModel): string | null {
  return model.mesh ? formatDims(model.mesh.bbox_mm, "mm") : null;
}

/** Имя файла для шапки страницы загрузки после «Заказать»: совпадает с тем, что делает API. */
export function uploadNameFor(model: CatalogModel): string {
  return `${model.title}.${model.ext}`;
}
