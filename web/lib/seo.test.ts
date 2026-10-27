import { describe, expect, it } from "vitest";
import type { Editor, EditorParam } from "./editors";
import {
  absoluteUrl,
  checkText,
  editorJsonLd,
  isNoindexSite,
  metaDescription,
  pageMetadata,
  paramDefaultText,
  paramRangeText,
  PRIVATE_PATHS,
  robotsRules,
  sitemapEntries,
  siteUrl,
  STATIC_PAGES,
} from "./seo";

const num = (over: Partial<EditorParam>): EditorParam => ({
  name: "outer_d",
  label: "Внешний диаметр",
  type: "number",
  default: 20,
  hint: "",
  unit: "мм",
  min: 4,
  max: 200,
  step: 0.5,
  integer: false,
  options: [],
  maxlen: 0,
  ...over,
});

const editor: Editor = {
  slug: "spacer",
  title: "Втулка / проставка",
  text: "Кольцо или шестигранник с отверстием.\n",
  material: "PETG",
  scad: "model.scad",
  order: 10,
  scad_ready: true,
  params: [
    num({}),
    num({ name: "count", label: "Число отверстий", min: 0, max: 4, step: 1, integer: true, default: 2, unit: "" }),
    num({ name: "hex", label: "Шестигранник", type: "bool", default: false, unit: "" }),
    num({
      name: "shape",
      label: "Форма",
      type: "choice",
      default: "round",
      unit: "",
      options: [
        { value: "round", label: "Круглая" },
        { value: "hex", label: "Шестигранник" },
      ],
    }),
    num({ name: "text", label: "Надпись", type: "text", default: "", unit: "", maxlen: 30 }),
  ],
  checks: [{ rule: "inner_d < outer_d", message: "Отверстие должно быть меньше внешнего диаметра." }],
};

describe("siteUrl", () => {
  it("берёт origin из SITE_URL без хвостов", () => {
    expect(siteUrl("https://tuc.ru/")).toBe("https://tuc.ru");
    expect(siteUrl("https://tuc.ru/some/path?x=1")).toBe("https://tuc.ru");
    expect(siteUrl("  http://localhost:8080  ")).toBe("http://localhost:8080");
  });

  it("пусто или мусор → localhost, чтобы dev и тесты работали", () => {
    expect(siteUrl(undefined)).toBe("http://localhost:8080");
    expect(siteUrl("")).toBe("http://localhost:8080");
    expect(siteUrl("tuc.ru")).toBe("http://localhost:8080");
    expect(siteUrl("ftp://tuc.ru")).toBe("http://localhost:8080");
  });

  it("absoluteUrl склеивает путь с адресом", () => {
    expect(absoluteUrl("/editors/spacer", "https://tuc.ru")).toBe("https://tuc.ru/editors/spacer");
    expect(absoluteUrl("editors", "https://tuc.ru")).toBe("https://tuc.ru/editors");
    expect(absoluteUrl("/", "https://tuc.ru")).toBe("https://tuc.ru/");
  });
});

describe("robots", () => {
  it("прод: всё открыто кроме личного, есть ссылка на sitemap", () => {
    const r = robotsRules("https://tuc.ru");
    expect(r.sitemap).toBe("https://tuc.ru/sitemap.xml");
    const rule = r.rules as { allow: string; disallow: string[] };
    expect(rule.allow).toBe("/");
    expect(rule.disallow).toEqual(PRIVATE_PATHS);
    expect(rule.disallow).toContain("/admin");
    expect(rule.disallow).toContain("/order/");
    expect(rule.disallow).toContain("/upload/");
    expect(rule.disallow).toContain("/account");
    // сама страница загрузки открыта — закрыты только личные /upload/<id>
    expect(rule.disallow).not.toContain("/upload");
  });

  it("staging и localhost закрыты целиком", () => {
    expect(isNoindexSite("https://staging.tuc.ru")).toBe(true);
    expect(isNoindexSite("http://localhost:8080")).toBe(true);
    expect(isNoindexSite("https://tuc.ru")).toBe(false);
    expect(isNoindexSite("https://www.tuc.ru")).toBe(false);
    const r = robotsRules("https://staging.tuc.ru");
    expect(r.sitemap).toBeUndefined();
    expect((r.rules as { disallow: string }).disallow).toBe("/");
  });
});

describe("sitemap", () => {
  it("статика + редакторы + модели каталога, абсолютные адреса", () => {
    const entries = sitemapEntries([{ slug: "spacer" }, { slug: "bracket" }], [{ slug: "hook" }], "https://tuc.ru");
    const urls = entries.map((e) => e.url);
    expect(urls.slice(0, STATIC_PAGES.length)).toEqual(STATIC_PAGES.map((p) => `https://tuc.ru${p.path}`));
    expect(urls).toContain("https://tuc.ru/editors/spacer");
    expect(urls).toContain("https://tuc.ru/editors/bracket");
    expect(urls).toContain("https://tuc.ru/catalog/hook");
    expect(urls).toHaveLength(STATIC_PAGES.length + 3);
    expect(new Set(urls).size).toBe(urls.length);
    // главная важнее всех, документы — меньше всех
    const byUrl = Object.fromEntries(entries.map((e) => [e.url, e.priority]));
    expect(byUrl["https://tuc.ru/"]).toBe(1);
    expect(byUrl["https://tuc.ru/offer"]).toBeLessThan(byUrl["https://tuc.ru/editors/spacer"]!);
  });

  it("без API — только статика, личные страницы не попадают", () => {
    const urls = sitemapEntries(null, null, "https://tuc.ru").map((e) => e.url);
    expect(urls).toHaveLength(STATIC_PAGES.length);
    for (const u of urls) {
      for (const p of PRIVATE_PATHS) expect(u.startsWith(`https://tuc.ru${p}`)).toBe(false);
    }
  });
});

describe("метатеги", () => {
  it("pageMetadata: canonical и Open Graph c абсолютными адресами", () => {
    const m = pageMetadata({ path: "/editors/spacer", title: "Втулка", description: "Описание", image: "/api/x.png" });
    expect(m.title).toBe("Втулка");
    expect(m.alternates?.canonical).toBe("http://localhost:8080/editors/spacer");
    const og = m.openGraph as { url: string; siteName: string; locale: string; images: { url: string }[] };
    expect(og.url).toBe("http://localhost:8080/editors/spacer");
    expect(og.siteName).toBe("BroPrint");
    expect(og.locale).toBe("ru_RU");
    expect(og.images[0]!.url).toBe("http://localhost:8080/api/x.png");
    expect((pageMetadata({ path: "/", title: "t", description: "d" }).openGraph as { images?: unknown }).images).toBeUndefined();
  });

  it("metaDescription: одна строка, не длиннее 160, fallback для пустого", () => {
    expect(metaDescription("Кольцо\n  с отверстием.\n", "x")).toBe("Кольцо с отверстием.");
    expect(metaDescription("  \n", "Запасной текст")).toBe("Запасной текст");
    const long = metaDescription(`${"слово ".repeat(40)}конец`, "x");
    expect(long.length).toBeLessThanOrEqual(160);
    expect(long.endsWith("…")).toBe(true);
    expect(long).not.toMatch(/слов…$/); // режем по слову, а не посреди
  });
});

describe("таблица параметров", () => {
  it("диапазоны словами", () => {
    expect(paramRangeText(num({}))).toBe("4–200 мм, шаг 0,5");
    expect(paramRangeText(num({ step: 1 }))).toBe("4–200 мм");
    expect(paramRangeText(num({ integer: true, min: 0, max: 4, unit: "" }))).toBe("0–4, целое");
    expect(paramRangeText(num({ min: 2, max: null, step: null }))).toBe("от 2 мм");
    expect(paramRangeText(num({ min: null, max: 10, step: null }))).toBe("до 10 мм");
    expect(paramRangeText(num({ min: null, max: null, step: null, unit: "" }))).toBe("число");
    expect(paramRangeText(editor.params[2]!)).toBe("да / нет");
    expect(paramRangeText(editor.params[3]!)).toBe("Круглая / Шестигранник");
    expect(paramRangeText(editor.params[4]!)).toBe("текст до 30 символов");
  });

  it("умолчания словами", () => {
    expect(paramDefaultText(num({}))).toBe("20 мм");
    expect(paramDefaultText(num({ default: 8.5 }))).toBe("8,5 мм");
    expect(paramDefaultText(editor.params[1]!)).toBe("2");
    expect(paramDefaultText(editor.params[2]!)).toBe("нет");
    expect(paramDefaultText(num({ type: "bool", default: true }))).toBe("да");
    expect(paramDefaultText(editor.params[3]!)).toBe("Круглая");
    expect(paramDefaultText(editor.params[4]!)).toBe("—");
    expect(paramDefaultText(num({ type: "text", default: "ТУЦ", maxlen: 30 }))).toBe("«ТУЦ»");
  });

  it("правило — текстом ошибки без точки", () => {
    expect(checkText(editor.checks[0]!)).toBe("Отверстие должно быть меньше внешнего диаметра");
  });
});

describe("JSON-LD", () => {
  it("хлебные крошки до редактора и веб-приложение с его адресом", () => {
    const [crumbs, app] = editorJsonLd(editor, "https://tuc.ru") as [
      { "@type": string; itemListElement: { position: number; item: string; name: string }[] },
      { "@type": string; url: string; name: string; description: string },
    ];
    expect(crumbs["@type"]).toBe("BreadcrumbList");
    expect(crumbs.itemListElement.map((i) => i.item)).toEqual([
      "https://tuc.ru/",
      "https://tuc.ru/editors",
      "https://tuc.ru/editors/spacer",
    ]);
    expect(crumbs.itemListElement[2]!.name).toBe("Втулка / проставка");
    expect(app["@type"]).toBe("WebApplication");
    expect(app.url).toBe("https://tuc.ru/editors/spacer");
    expect(app.name).toContain("Втулка / проставка");
    expect(app.description).toBe("Кольцо или шестигранник с отверстием.");
    // в HTML попадёт через JSON.stringify — не должно падать и не должно содержать undefined
    expect(JSON.stringify(editorJsonLd(editor))).not.toContain("undefined");
  });
});
