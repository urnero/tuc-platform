import { describe, expect, it } from "vitest";
import { formatPrice } from "./format";

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
