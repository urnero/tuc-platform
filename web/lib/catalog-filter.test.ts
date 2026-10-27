import { describe, expect, it } from "vitest";
import { type Catalog, type CatalogModel, filterModels, filterQuery, materialsOf, modelsWord, parseFilter } from "./catalog";

const model = (slug: string, category: string, material: string): CatalogModel => ({
  slug,
  title: slug,
  category,
  text: "",
  file: `${slug}.stl`,
  ext: "stl",
  material,
  license: "",
  preview_url: "",
  file_url: "",
  mesh: null,
});

const catalog: Catalog = {
  categories: [
    { slug: "home", title: "Для дома", text: "", count: 2 },
    { slug: "hardware", title: "Крепёж", text: "", count: 1 },
  ],
  models: [model("a", "home", "PLA"), model("b", "hardware", "PETG"), model("c", "home", "PETG")],
};

describe("фильтр каталога (B43)", () => {
  it("materialsOf — без повторов, в порядке yaml", () => {
    expect(materialsOf(catalog.models)).toEqual(["PLA", "PETG"]);
  });

  it("filterModels — по категории, материалу и обоим сразу", () => {
    expect(filterModels(catalog.models, { category: "", material: "" }).map((m) => m.slug)).toEqual(["a", "b", "c"]);
    expect(filterModels(catalog.models, { category: "home", material: "" }).map((m) => m.slug)).toEqual(["a", "c"]);
    expect(filterModels(catalog.models, { category: "", material: "PETG" }).map((m) => m.slug)).toEqual(["b", "c"]);
    expect(filterModels(catalog.models, { category: "home", material: "PETG" }).map((m) => m.slug)).toEqual(["c"]);
  });

  it("parseFilter — знакомые значения из адреса, мусор отбрасываем", () => {
    expect(parseFilter("?cat=home&mat=PETG", catalog)).toEqual({ category: "home", material: "PETG" });
    expect(parseFilter("?cat=nope&mat=ABS", catalog)).toEqual({ category: "", material: "" });
    expect(parseFilter("", catalog)).toEqual({ category: "", material: "" });
  });

  it("filterQuery — обратно в адрес", () => {
    expect(filterQuery({ category: "home", material: "PETG" })).toBe("?cat=home&mat=PETG");
    expect(filterQuery({ category: "", material: "PLA" })).toBe("?mat=PLA");
    expect(filterQuery({ category: "", material: "" })).toBe("");
  });

  it("modelsWord — склонение", () => {
    expect([1, 2, 5, 11, 12, 21, 22, 25, 111].map(modelsWord)).toEqual([
      "модель", "модели", "моделей", "моделей", "моделей", "модель", "модели", "моделей", "моделей",
    ]);
  });
});
