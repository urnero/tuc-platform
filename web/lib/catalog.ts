/**
 * Каталог готовых моделей (B20): типы ответа GET /api/v1/catalog и помощники для страниц
 * /catalog и /catalog/[slug]. Данные приходят из catalog/catalog.yaml через API;
 * страницы кэшируются на 10 минут (ISR) — владелец правит yaml, сайт подхватывает сам.
 */

import { apiInternalUrl } from "./landing";
import { formatPrice } from "./format";
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
  /**
   * Ориентир цены одной штуки до слайсера (api/app/pricing.py::estimate_price): по объёму сетки,
   * самовывоз, без постобработки. null — нет сетки или прайса. Старый API поля не отдаёт.
   */
  price?: CatalogPrice | null;
};

export type CatalogPrice = {
  total: number;
  /** В каком материале посчитано (материал модели или PLA, если он «по запросу»). */
  material: string;
  /** Одна штука упирается в минимальный заказ — честнее писать «от N ₽». */
  min_order: boolean;
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

/** Фильтр каталога (B43): пустая строка = «все». */
export type CatalogFilter = { category: string; material: string };

export const NO_FILTER: CatalogFilter = { category: "", material: "" };

/** Материалы, которые есть в каталоге, — для кнопок фильтра. Порядок — как встречаются в yaml. */
export function materialsOf(models: CatalogModel[]): string[] {
  return [...new Set(models.map((m) => m.material).filter(Boolean))];
}

/** Модели под выбранные категорию и материал. */
export function filterModels(models: CatalogModel[], f: CatalogFilter): CatalogModel[] {
  return models.filter((m) => (!f.category || m.category === f.category) && (!f.material || m.material === f.material));
}

/**
 * Фильтр из адреса страницы (?cat=…&mat=…), чтобы ссылкой можно было поделиться.
 * Незнакомые значения отбрасываем — покажем всё, а не пустую страницу.
 */
export function parseFilter(search: string, catalog: Catalog): CatalogFilter {
  const q = new URLSearchParams(search);
  const cat = q.get("cat") ?? "";
  const mat = q.get("mat") ?? "";
  return {
    category: catalog.categories.some((c) => c.slug === cat) ? cat : "",
    material: materialsOf(catalog.models).includes(mat) ? mat : "",
  };
}

/** Фильтр → строка адреса: «?cat=home&mat=PETG», без фильтра — пусто. */
export function filterQuery(f: CatalogFilter): string {
  const q = new URLSearchParams();
  if (f.category) q.set("cat", f.category);
  if (f.material) q.set("mat", f.material);
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** Склонение для счётчика: 1 модель, 2 модели, 5 моделей. */
export function modelsWord(n: number): string {
  const d10 = n % 10;
  const d100 = n % 100;
  if (d10 === 1 && d100 !== 11) return "модель";
  if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return "модели";
  return "моделей";
}

/**
 * Цена для карточки: «от 400 ₽» (упёрлись в минимальный заказ) или «≈ 580 ₽».
 * Нет ориентира — null, карточка показывает только габариты.
 */
export function priceText(model: CatalogModel): string | null {
  const p = model.price;
  if (!p || p.total <= 0) return null;
  return `${p.min_order ? "от" : "≈"} ${formatPrice(p.total)}`;
}

/**
 * Пример цены для главной: самая дешёвая модель каталога с ориентиром —
 * «Подставка под кружку — от 400 ₽». Каталога или цен нет — null (строка не показывается).
 */
export function priceExample(catalog: Catalog | null): { slug: string; text: string } | null {
  const priced = (catalog?.models ?? []).filter((m) => priceText(m) !== null);
  if (priced.length === 0) return null;
  const cheapest = priced.reduce((a, b) => ((b.price?.total ?? 0) < (a.price?.total ?? 0) ? b : a));
  return { slug: cheapest.slug, text: `${cheapest.title} — ${priceText(cheapest)}` };
}
