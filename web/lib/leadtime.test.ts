import { describe, expect, it } from "vitest";
import { leadTimeDays, leadTimeText } from "./leadtime";

const H = 3600;

describe("leadTimeDays", () => {
  it("небольшая деталь — 1–3 дня, как на главной", () => {
    expect(leadTimeDays(2 * H, 1)).toEqual({ min: 1, max: 3 });
    expect(leadTimeDays(19 * H, 1)).toEqual({ min: 1, max: 3 });
  });

  it("крупная деталь — больше суток печати на одном принтере", () => {
    expect(leadTimeDays(45 * H, 1)).toEqual({ min: 3, max: 5 });
  });

  it("тираж раскладывается на 3 принтера", () => {
    // 50 шт × 1 ч = 50 ч / (20 ч × 3) → 1 день
    expect(leadTimeDays(H, 50)).toEqual({ min: 1, max: 3 });
    // 100 шт × 2 ч = 200 ч / 60 → 4 дня
    expect(leadTimeDays(2 * H, 100)).toEqual({ min: 4, max: 6 });
  });

  it("обработка добавляет дни", () => {
    expect(leadTimeDays(2 * H, 1, "sanding")).toEqual({ min: 2, max: 4 });
    expect(leadTimeDays(2 * H, 1, "painting")).toEqual({ min: 3, max: 5 });
    expect(leadTimeDays(2 * H, 1, "unknown")).toEqual({ min: 1, max: 3 });
  });

  it("пустые данные — null", () => {
    expect(leadTimeDays(0, 1)).toBeNull();
    expect(leadTimeDays(NaN, 1)).toBeNull();
    expect(leadTimeDays(H, 0)).toBeNull();
  });
});

describe("leadTimeText", () => {
  it("форма слова по верхнему числу", () => {
    expect(leadTimeText(2 * H, 1)).toBe("Готово через 1–3 рабочих дня");
    expect(leadTimeText(2 * H, 100)).toBe("Готово через 4–6 рабочих дней");
    expect(leadTimeText(0, 1)).toBeNull();
  });
});
