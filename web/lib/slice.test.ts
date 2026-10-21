import { describe, expect, it } from "vitest";
import { formatDuration, formatGrams } from "./slice";

describe("formatDuration", () => {
  it("часы и минуты", () => {
    expect(formatDuration(3723)).toBe("1 ч 3 мин");
  });
  it("меньше минуты — 1 мин", () => {
    expect(formatDuration(30)).toBe("1 мин");
  });
  it("только минуты", () => {
    expect(formatDuration(45 * 60)).toBe("45 мин");
  });
  it("ровно часы", () => {
    expect(formatDuration(2 * 3600)).toBe("2 ч");
  });
  it("59 мин 50 с округляет до следующего часа", () => {
    expect(formatDuration(3600 + 59 * 60 + 50)).toBe("2 ч");
  });
  it("дни", () => {
    expect(formatDuration(2 * 86400 + 3 * 3600 + 100)).toBe("2 д 3 ч");
  });
});

describe("formatGrams", () => {
  it("меньше 10 г — с десятыми", () => {
    expect(formatGrams(8.89)).toBe("8,9 г");
  });
  it("больше 10 г — целые", () => {
    expect(formatGrams(123.4)).toBe("123 г");
  });
});
