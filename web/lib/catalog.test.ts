import { afterEach, describe, expect, it, vi } from "vitest";
import { type Catalog, type CatalogModel, dimsText, groupByCategory, loadCatalogModel, uploadNameFor } from "./catalog";

const model = (slug: string, category: string, extra: Partial<CatalogModel> = {}): CatalogModel => ({
  slug,
  title: slug,
  category,
  text: "",
  file: `${slug}.stl`,
  ext: "stl",
  material: "PLA",
  license: "",
  preview_url: `/api/v1/catalog/${slug}/preview.png`,
  file_url: `/api/v1/catalog/${slug}/file`,
  mesh: null,
  ...extra,
});

const catalog: Catalog = {
  categories: [
    { slug: "home", title: "Для дома", text: "", count: 2 },
    { slug: "empty", title: "Пустая", text: "", count: 0 },
    { slug: "hardware", title: "Крепёж", text: "", count: 1 },
  ],
  models: [model("a", "home"), model("b", "hardware"), model("c", "home"), model("d", "ghost")],
};

describe("groupByCategory", () => {
  it("порядок категорий из yaml, пустые и неизвестные категории не показываем", () => {
    const groups = groupByCategory(catalog);
    expect(groups.map((g) => g.category.slug)).toEqual(["home", "hardware"]);
    expect(groups[0].models.map((m) => m.slug)).toEqual(["a", "c"]);
    expect(groups[1].models.map((m) => m.slug)).toEqual(["b"]);
  });
});

describe("dimsText", () => {
  it("габариты в мм; без сетки — null", () => {
    const mesh = {
      triangles: 12, vertices: 8, bbox_mm: { x: 90, y: 90, z: 7 }, volume_cm3: 40, surface_cm2: 10,
      watertight: true, repaired: false, unit_hint: "mm" as const, warnings: [],
    };
    expect(dimsText(model("x", "home", { mesh }))).toBe("90 × 90 × 7 мм");
    expect(dimsText(model("x", "home"))).toBeNull();
  });
});

describe("uploadNameFor", () => {
  it("название + расширение, как в API", () => {
    expect(uploadNameFor(model("x", "home", { title: "Кубик", ext: "3mf" }))).toBe("Кубик.3mf");
  });
});

describe("loadCatalogModel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("кривой slug не уходит в API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect(await loadCatalogModel("../admin")).toBeNull();
    expect(await loadCatalogModel("Кубик")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("404 и ошибка сети → null, 200 → модель", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    expect(await loadCatalogModel("nope")).toBeNull();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down"); }));
    expect(await loadCatalogModel("cube")).toBeNull();
    const body = JSON.stringify(model("cube", "home"));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    expect((await loadCatalogModel("cube"))?.slug).toBe("cube");
  });
});
