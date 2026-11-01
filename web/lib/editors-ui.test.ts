import { describe, expect, it } from "vitest";
import { AUTO_BUILD_MS, type EditorParam, hasSlider, rangeHint, sameParams, sliderStep, valueWithUnit } from "./editors";

const num = (extra: Partial<EditorParam> = {}): EditorParam => ({
  name: "d",
  label: "Диаметр",
  type: "number",
  default: 10,
  hint: "",
  unit: "мм",
  min: 4,
  max: 200,
  step: null,
  integer: false,
  options: [],
  maxlen: 40,
  ...extra,
});

describe("подписи и ползунки редактора (B43)", () => {
  it("hasSlider — только число с обеими границами", () => {
    expect(hasSlider(num())).toBe(true);
    expect(hasSlider(num({ max: null }))).toBe(false);
    expect(hasSlider(num({ type: "text" }))).toBe(false);
    expect(hasSlider(num({ min: 5, max: 5 }))).toBe(false);
  });

  it("sliderStep — из схемы, у целых 1, иначе по ширине диапазона", () => {
    expect(sliderStep(num({ step: 0.5 }))).toBe(0.5);
    expect(sliderStep(num({ integer: true }))).toBe(1);
    expect(sliderStep(num({ min: 0, max: 10 }))).toBe(0.1);
    expect(sliderStep(num({ min: 0, max: 80 }))).toBe(0.5);
    expect(sliderStep(num())).toBe(1);
  });

  it("rangeHint — диапазон с единицей и подсказка", () => {
    expect(rangeHint(num())).toBe("от 4 до 200 мм");
    expect(rangeHint(num({ hint: "внешний", min: 2.5 }))).toBe("от 2,5 до 200 мм · внешний");
    expect(rangeHint(num({ max: null }))).toBe("не меньше 4 мм");
    expect(rangeHint(num({ min: null }))).toBe("не больше 200 мм");
    expect(rangeHint(num({ type: "text", hint: "до 20 букв" }))).toBe("до 20 букв");
  });

  it("sameParams — сравнение построенных и текущих параметров", () => {
    expect(sameParams({ d: 10, h: true }, { d: 10, h: true })).toBe(true);
    expect(sameParams({ d: 10 }, { d: 11 })).toBe(false);
    expect(sameParams({ d: 10 }, { d: 10, h: 1 })).toBe(false);
    expect(sameParams(null, { d: 10 })).toBe(false);
  });
});

describe("живое превью (B67)", () => {
  it("пересборка через 300 мс после правки", () => {
    expect(AUTO_BUILD_MS).toBe(300);
  });

  it("valueWithUnit — число с единицей, запятая, пусто — прочерк", () => {
    expect(valueWithUnit(num(), "20")).toBe("20 мм");
    expect(valueWithUnit(num(), "12.5")).toBe("12,5 мм");
    expect(valueWithUnit(num({ unit: "" }), "3")).toBe("3");
    expect(valueWithUnit(num(), "")).toBe("—");
  });
});
