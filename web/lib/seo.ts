/**
 * SEO (B25): адрес сайта, канонические ссылки, Open Graph, sitemap.xml, robots.txt
 * и текст для поисковиков на страницах редакторов.
 *
 * Адрес сайта берётся из SITE_URL (та же переменная, что у API в .env; в web её
 * передаёт docker-compose — и при сборке образа, и при запуске). Без неё — localhost,
 * чтобы `npm run dev` и тесты работали без настроек.
 *
 * Здесь только чистые функции без Next — их проверяют тесты (lib/seo.test.ts);
 * сами маршруты sitemap.xml и robots.txt — тонкие обёртки в app/sitemap.ts и app/robots.ts.
 */

import type { Metadata, MetadataRoute } from "next";
import type { EditorCheck, EditorParam, Editor } from "./editors";
import { fmt } from "./editors";

export const SITE_NAME = "ТУЦ";
const DEFAULT_SITE_URL = "http://localhost:8080";

/** Внешний адрес сайта без завершающего слэша: «https://tuc.ru». Мусор в SITE_URL → localhost. */
export function siteUrl(env: string | undefined = process.env.SITE_URL): string {
  const raw = (env ?? "").trim();
  if (!raw) return DEFAULT_SITE_URL;
  try {
    const u = new URL(raw);
    if (u.protocol !== "http:" && u.protocol !== "https:") return DEFAULT_SITE_URL;
    return u.origin;
  } catch {
    return DEFAULT_SITE_URL;
  }
}

/** «/editors/spacer» → «https://tuc.ru/editors/spacer». */
export function absoluteUrl(path: string, base: string = siteUrl()): string {
  return path === "/" ? `${base}/` : `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * Тестовый стенд — его поисковикам показывать не надо. Признак — хост `staging.<домен>`
 * (так его называет deploy/bootstrap.sh) или localhost; общий Caddy ещё и отдаёт
 * заголовок X-Robots-Tag: noindex, это вторая линия.
 */
export function isNoindexSite(base: string = siteUrl()): boolean {
  const host = new URL(base).hostname;
  return host.startsWith("staging.") || host === "localhost" || host === "127.0.0.1";
}

/** Метатеги страницы одним вызовом: канонический адрес + карточка для соцсетей и мессенджеров. */
export function pageMetadata(opts: {
  path: string;
  title: string;
  description: string;
  /** Картинка для карточки (абсолютный адрес или путь от корня сайта). */
  image?: string;
}): Metadata {
  const url = absoluteUrl(opts.path);
  return {
    title: opts.title,
    description: opts.description,
    alternates: { canonical: url },
    openGraph: {
      title: opts.title,
      description: opts.description,
      url,
      siteName: SITE_NAME,
      locale: "ru_RU",
      type: "website",
      ...(opts.image ? { images: [{ url: absoluteUrl(opts.image) }] } : {}),
    },
  };
}

/** Описание из yaml (`text: >` даёт перенос в конце) — в одну строку и не длиннее 160 символов. */
export function metaDescription(text: string, fallback: string): string {
  const one = text.replace(/\s+/g, " ").trim() || fallback;
  if (one.length <= 160) return one;
  const cut = one.slice(0, 157);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), 100))}…`;
}

/** Публичные страницы без параметров: путь, важность, как часто меняются. */
export const STATIC_PAGES: { path: string; priority: number; changeFrequency: "weekly" | "monthly" | "yearly" }[] = [
  { path: "/", priority: 1, changeFrequency: "weekly" },
  { path: "/editors", priority: 0.9, changeFrequency: "weekly" },
  { path: "/catalog", priority: 0.9, changeFrequency: "weekly" },
  { path: "/upload", priority: 0.8, changeFrequency: "monthly" },
  { path: "/about", priority: 0.5, changeFrequency: "monthly" },
  { path: "/contacts", priority: 0.5, changeFrequency: "monthly" },
  { path: "/offer", priority: 0.3, changeFrequency: "yearly" },
  { path: "/policy", priority: 0.3, changeFrequency: "yearly" },
];

/**
 * Строки sitemap.xml: статические страницы + редактор на каждый `editors/<slug>/` +
 * модель на каждую строку каталога. Списки null (API не ответил) → только статика.
 */
export function sitemapEntries(
  editors: { slug: string }[] | null,
  models: { slug: string }[] | null,
  base: string = siteUrl(),
): MetadataRoute.Sitemap {
  const entries: MetadataRoute.Sitemap = STATIC_PAGES.map((p) => ({
    url: absoluteUrl(p.path, base),
    priority: p.priority,
    changeFrequency: p.changeFrequency,
  }));
  for (const e of editors ?? []) {
    entries.push({ url: absoluteUrl(`/editors/${e.slug}`, base), priority: 0.8, changeFrequency: "monthly" });
  }
  for (const m of models ?? []) {
    entries.push({ url: absoluteUrl(`/catalog/${m.slug}`, base), priority: 0.7, changeFrequency: "monthly" });
  }
  return entries;
}

/** Что закрыто от роботов: админка, API, страницы заказов и загрузок по личным ссылкам. */
export const PRIVATE_PATHS = ["/admin", "/api/", "/order/", "/upload/", "/account"];

/** robots.txt: на проде — всё открыто кроме личного, на staging/localhost — закрыто целиком. */
export function robotsRules(base: string = siteUrl()): MetadataRoute.Robots {
  if (isNoindexSite(base)) {
    return { rules: { userAgent: "*", disallow: "/" } };
  }
  return {
    rules: { userAgent: "*", allow: "/", disallow: PRIVATE_PATHS },
    sitemap: absoluteUrl("/sitemap.xml", base),
  };
}

/** Диапазон параметра словами для таблицы на странице редактора: «15–200 мм, шаг 0,5». */
export function paramRangeText(p: EditorParam): string {
  if (p.type === "bool") return "да / нет";
  if (p.type === "choice") return p.options.map((o) => o.label).join(" / ");
  if (p.type === "text") return `текст до ${p.maxlen} символов`;
  const unit = p.unit ? ` ${p.unit}` : "";
  let range: string;
  if (p.min !== null && p.max !== null) range = `${fmt(p.min)}–${fmt(p.max)}${unit}`;
  else if (p.min !== null) range = `от ${fmt(p.min)}${unit}`;
  else if (p.max !== null) range = `до ${fmt(p.max)}${unit}`;
  else range = `число${unit ? `,${unit}` : ""}`;
  if (p.integer) range += ", целое";
  else if (p.step !== null && p.step !== 1) range += `, шаг ${fmt(p.step)}`;
  return range;
}

/** Значение по умолчанию словами: число с единицей, «да»/«нет», подпись варианта, текст. */
export function paramDefaultText(p: EditorParam): string {
  if (p.type === "bool") return p.default ? "да" : "нет";
  if (p.type === "choice") return p.options.find((o) => o.value === String(p.default))?.label ?? String(p.default);
  if (p.type === "text") return String(p.default).trim() ? `«${String(p.default)}»` : "—";
  return `${fmt(Number(p.default))}${p.unit ? ` ${p.unit}` : ""}`;
}

/** Правило между параметрами — текстом ошибки, он и есть понятная формулировка. */
export function checkText(c: EditorCheck): string {
  return c.message.replace(/\.\s*$/, "");
}

/**
 * Структурированные данные (schema.org, JSON-LD) для страницы редактора: хлебные крошки
 * и сама страница как «веб-приложение» — поисковик понимает, что это инструмент, а не статья.
 */
export function editorJsonLd(editor: Editor, base: string = siteUrl()): object[] {
  const url = absoluteUrl(`/editors/${editor.slug}`, base);
  return [
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: SITE_NAME, item: absoluteUrl("/", base) },
        { "@type": "ListItem", position: 2, name: "Редакторы деталей", item: absoluteUrl("/editors", base) },
        { "@type": "ListItem", position: 3, name: editor.title, item: url },
      ],
    },
    {
      "@context": "https://schema.org",
      "@type": "WebApplication",
      name: `${editor.title} — 3D-печать по вашим размерам`,
      url,
      applicationCategory: "DesignApplication",
      operatingSystem: "Web",
      inLanguage: "ru",
      description: metaDescription(editor.text, `Редактор «${editor.title}»: задайте размеры — модель построится сразу.`),
      offers: { "@type": "Offer", price: "0", priceCurrency: "RUB", description: "Построение модели бесплатно, печать — по расчёту" },
    },
  ];
}
