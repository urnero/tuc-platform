/**
 * /sitemap.xml (B25): статические страницы + все редакторы + все модели каталога.
 * Списки берутся с API и кэшируются на 10 минут (ISR), как сами страницы: владелец
 * добавил папку в editors/ или строку в catalog.yaml — карта обновится сама.
 * При сборке образа API недоступен — карта будет из статики, пока не пройдёт первое обновление.
 */

import type { MetadataRoute } from "next";
import { loadCatalog } from "@/lib/catalog";
import { loadEditors } from "@/lib/editors";
import { sitemapEntries } from "@/lib/seo";

export const revalidate = 600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [editors, catalog] = await Promise.all([loadEditors(), loadCatalog()]);
  return sitemapEntries(editors, catalog?.models ?? null);
}
