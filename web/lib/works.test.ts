import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { type Work, WORKS, workImageUrl, worksTitle } from "./works";

const PUBLIC_WORKS = path.join(__dirname, "..", "public", "works");

describe("WORKS", () => {
  it("каждая карточка заполнена, материал — один из профилей", () => {
    expect(WORKS.length).toBeGreaterThanOrEqual(3);
    for (const w of WORKS) {
      expect(w.title.trim()).not.toBe("");
      expect(w.text.trim()).not.toBe("");
      expect(["PLA", "PETG", "ABS"]).toContain(w.material);
    }
  });
  it("каждое указанное фото действительно лежит в web/public/works", () => {
    for (const w of WORKS) {
      if (w.image) expect(existsSync(path.join(PUBLIC_WORKS, w.image)), `нет файла public/works/${w.image}`).toBe(true);
    }
  });
});

describe("workImageUrl", () => {
  const base: Work = { title: "т", text: "т", material: "PLA", image: null };
  it("имя файла → путь /works/…; пусто или пробелы → null", () => {
    expect(workImageUrl({ ...base, image: "korpus.jpg" })).toBe("/works/korpus.jpg");
    expect(workImageUrl(base)).toBeNull();
    expect(workImageUrl({ ...base, image: "  " })).toBeNull();
  });
});

describe("worksTitle", () => {
  const base: Work = { title: "т", text: "т", material: "PLA", image: null };
  it("без фото — «Что печатаем», с хотя бы одним — «Примеры работ»", () => {
    expect(worksTitle([base, base])).toBe("Что печатаем");
    expect(worksTitle([base, { ...base, image: "a.jpg" }])).toBe("Примеры работ");
  });
});
