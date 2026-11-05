import { describe, expect, it } from "vitest";
import { AUTO_3D_MIN_WIDTH, placeholderHeight, shouldAutoLoad3D } from "./viewer";

describe("shouldAutoLoad3D", () => {
  it("десктоп — грузим сами", () => {
    expect(shouldAutoLoad3D({ width: 1440 })).toBe(true);
    expect(shouldAutoLoad3D({ width: AUTO_3D_MIN_WIDTH })).toBe(true);
  });
  it("телефон — только по кнопке", () => {
    expect(shouldAutoLoad3D({ width: 390 })).toBe(false);
    expect(shouldAutoLoad3D({ width: AUTO_3D_MIN_WIDTH - 1 })).toBe(false);
  });
  it("экономия трафика — по кнопке даже на десктопе", () => {
    expect(shouldAutoLoad3D({ width: 1440, saveData: true })).toBe(false);
  });
});

describe("placeholderHeight", () => {
  it("десктоп — как готовый просмотр, телефон — короткая карточка", () => {
    expect(placeholderHeight(true)).toBe(420);
    expect(placeholderHeight(false)).toBe(160);
    expect(placeholderHeight(false, 120)).toBe(120);
  });
});
