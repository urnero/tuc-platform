import { describe, expect, it } from "vitest";
import {
  defaultColors,
  distinctCount,
  type PaintColor,
  type Part,
  partCaption,
  partRanges,
  plural,
  summaryLine,
  validateColors,
} from "./paint";

const PALETTE: PaintColor[] = [
  { key: "red", name: "Красный", hex: "#D32F2F" },
  { key: "blue", name: "Синий", hex: "#1976D2" },
];

function part(i: number, faces: number, first: number, merged = 0): Part {
  return {
    index: i,
    name: merged ? `Мелкие детали (${merged} шт.)` : `Деталь ${i + 1}`,
    faces,
    first_face: first,
    volume_cm3: 24,
    bbox_mm: { x: 40, y: 30.25, z: 20 },
    merged,
  };
}

const PARTS = [part(0, 12, 0), part(1, 1280, 12), part(2, 128, 1292, 3)];

describe("defaultColors", () => {
  it("раздаёт палитру по кругу", () => {
    expect(defaultColors(PARTS, PALETTE)).toEqual(["red", "blue", "red"]);
    expect(defaultColors(PARTS, [])).toEqual(["", "", ""]);
  });
});

describe("validateColors", () => {
  it("всё выбрано — ошибки нет", () => {
    expect(validateColors(["red", "blue", "red"], PARTS, PALETTE)).toBeNull();
  });
  it("не хватает цвета или цвет не из палитры", () => {
    expect(validateColors(["red"], PARTS, PALETTE)).toBe("Выберите цвет для каждой детали.");
    expect(validateColors(["red", "", "red"], PARTS, PALETTE)).toBe("Выберите цвет для детали «Деталь 2».");
    expect(validateColors(["red", "pink", "red"], PARTS, PALETTE)).toContain("Деталь 2");
    expect(validateColors([], [], PALETTE)).toBe("В модели нет деталей.");
  });
});

describe("partRanges", () => {
  it("диапазоны треугольников с hex выбранного цвета", () => {
    expect(partRanges(PARTS, ["red", "blue", "nope"], PALETTE, "#000000")).toEqual([
      { start: 0, count: 12, hex: "#D32F2F" },
      { start: 12, count: 1280, hex: "#1976D2" },
      { start: 1292, count: 128, hex: "#000000" },
    ]);
  });
});

describe("подписи", () => {
  it("plural", () => {
    expect([1, 2, 5, 11, 21, 22, 112].map((n) => plural(n, "деталь", "детали", "деталей"))).toEqual([
      "деталь",
      "детали",
      "деталей",
      "деталей",
      "деталь",
      "детали",
      "деталей",
    ]);
  });
  it("summaryLine и distinctCount", () => {
    expect(distinctCount(["red", "blue", "red", ""])).toBe(2);
    expect(summaryLine(PARTS, ["red", "blue", "red"])).toBe("3 детали, 2 цвета");
    expect(summaryLine([PARTS[0]], ["red"])).toBe("1 деталь, 1 цвет");
  });
  it("partCaption", () => {
    expect(partCaption(PARTS[0])).toBe("40 × 30,3 × 20 мм, 24,0 см³");
    expect(partCaption(PARTS[2])).toBe("24,0 см³ вместе");
  });
});
