import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Первый экран главной не должен возвращаться к старому списку «PLA · PETG · ABS» (после B44 пластиков больше).
describe("главная: список материалов", () => {
  it("упоминает нейлон, карбон и смолы", () => {
    const src = readFileSync(join(__dirname, "../app/page.tsx"), "utf8");
    expect(src).not.toContain("PLA · PETG · ABS");
    expect(src).toContain("нейлон, карбон, смолы");
  });
});
