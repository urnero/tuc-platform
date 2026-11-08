import { describe, expect, it } from "vitest";
import {
  WARNING_TEXT,
  DEFAULT_FORM,
  editorHref,
  embossWarningTexts,
  FACES,
  fmt,
  parseNumber,
  toParams,
  validateForm,
  validateLogoFile,
} from "./emboss";

describe("validateForm", () => {
  it("пустая надпись — ошибка, заполненная — нет", () => {
    expect(validateForm({ ...DEFAULT_FORM, text: "  " }, false)).toEqual({ text: "Введите надпись." });
    expect(validateForm({ ...DEFAULT_FORM, text: "ТУЦ" }, false)).toEqual({});
  });

  it("слишком длинная надпись", () => {
    expect(validateForm({ ...DEFAULT_FORM, text: "x".repeat(41) }, false)).toEqual({
      text: "Не длиннее 40 символов.",
    });
  });

  it("логотип без файла — ошибка, с файлом — текст не нужен", () => {
    expect(validateForm({ ...DEFAULT_FORM, kind: "logo" }, false)).toEqual({
      kind: "Сначала загрузите логотип (SVG).",
    });
    expect(validateForm({ ...DEFAULT_FORM, kind: "logo" }, true)).toEqual({});
  });

  it("числа: границы, запятая, мусор", () => {
    const errors = validateForm(
      { ...DEFAULT_FORM, text: "a", size_mm: "2", depth_mm: "11", dx: "abc", dy: "600", angle: "-181" },
      false,
    );
    expect(errors).toEqual({
      size_mm: "Не меньше 3 мм.",
      depth_mm: "Не больше 10 мм.",
      dx: "Нужно число.",
      dy: "Не больше 500 мм.",
      angle: "Не меньше -180 °.",
    });
    expect(validateForm({ ...DEFAULT_FORM, text: "a", size_mm: "12,5", depth_mm: "0,8" }, false)).toEqual({});
  });
});

describe("toParams", () => {
  it("числа становятся числами, текст обрезается, у логотипа текст пустой", () => {
    expect(toParams({ ...DEFAULT_FORM, text: " ТУЦ ", size_mm: "12,5", dx: "-3" })).toEqual({
      kind: "text",
      text: "ТУЦ",
      font: "sans",
      bold: true,
      size_mm: 12.5,
      depth_mm: 1,
      style: "raised",
      face: "front",
      dx: -3,
      dy: 0,
      angle: 0,
    });
    expect(toParams({ ...DEFAULT_FORM, kind: "logo", text: "лишнее" }).text).toBe("");
  });
});

describe("validateLogoFile", () => {
  it("только svg до 1 МБ", () => {
    expect(validateLogoFile("logo.svg", 100)).toBeNull();
    expect(validateLogoFile("LOGO.SVG", 100)).toBeNull();
    expect(validateLogoFile("logo.png", 100)).toMatch(/SVG/);
    expect(validateLogoFile("logo.svg", 0)).toBe("Файл пустой.");
    expect(validateLogoFile("logo.svg", 1024 * 1024 + 1)).toBe("Логотип больше 1 МБ.");
  });
});

describe("мелочи", () => {
  it("parseNumber и fmt", () => {
    expect(parseNumber("12,5")).toBe(12.5);
    expect(parseNumber("")).toBeNaN();
    expect(fmt(12.5)).toBe("12,5");
    expect(fmt(20)).toBe("20");
    expect(fmt(0.2)).toBe("0,2");
  });

  it("грани — все шесть, спереди первая", () => {
    expect(FACES.map((f) => f.value).sort()).toEqual(["back", "bottom", "front", "left", "right", "top"]);
    expect(FACES[0].value).toBe("front");
  });
});

describe("ссылка на редактор (B62a)", () => {
  it("без инструмента и сразу с инструментом «Логотип»", () => {
    expect(editorHref("abc")).toBe("/upload/abc/edit");
    expect(editorHref("abc", "logo")).toBe("/upload/abc/edit?tool=logo");
  });
});

describe("WARNING_TEXT", () => {
  it("есть понятный текст для всех предупреждений сервера", () => {
    for (const code of ["merged_without_boolean", "normal_flipped", "curved_surface", "edge_overhang"]) {
      expect(WARNING_TEXT[code]).toBeTruthy();
    }
  });
});

describe("embossWarningTexts (B66)", () => {
  it("коды сервера → слова, служебный merged_without_boolean скрыт, неизвестный — как есть", () => {
    expect(embossWarningTexts(["edge_overhang", "merged_without_boolean", "x_new"])).toEqual([
      WARNING_TEXT.edge_overhang,
      "x_new",
    ]);
    expect(embossWarningTexts(undefined)).toEqual([]);
  });
});
