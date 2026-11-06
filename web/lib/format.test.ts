import { describe, expect, it } from "vitest";
import { formatPrice, formatPriceExact } from "./format";

describe("formatPrice", () => {
  it("разделяет тысячи пробелом и добавляет ₽", () => {
    expect(formatPrice(2500)).toBe("2 500 ₽");
  });
  it("округляет до рубля", () => {
    expect(formatPrice(999.6)).toBe("1 000 ₽");
  });
  it("ноль", () => {
    expect(formatPrice(0)).toBe("0 ₽");
  });
});

describe("formatPriceExact", () => {
  it("копейки, если есть", () => {
    expect(formatPriceExact(77.15)).toBe("77,15 ₽");
    expect(formatPriceExact(3857.5)).toBe("3 857,50 ₽");
  });
  it("без копеек — как formatPrice", () => {
    expect(formatPriceExact(3086)).toBe("3 086 ₽");
    expect(formatPriceExact(3085.999)).toBe("3 086 ₽");
  });
});
