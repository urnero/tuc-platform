import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Допуск ±0,3 мм показывается у выбора материала в калькуляторе и обещан на /about —
// цифра должна совпадать в обоих местах.
const read = (p: string) => readFileSync(join(__dirname, "..", p), "utf8");

describe("подсказка о допуске", () => {
  it("калькулятор показывает допуск и ссылку на /about", () => {
    const src = read("components/SliceCalc.tsx");
    expect(src).toContain('data-testid="tolerance-hint"');
    expect(src).toContain("±0,3 мм");
    expect(src).toContain('href="/about"');
  });
  it("на /about та же цифра", () => {
    expect(read("app/about/page.tsx")).toContain("±0,3 мм");
  });
});
