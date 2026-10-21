import { describe, expect, it } from "vitest";
import { BENEFITS, formatPerGram, materialCards, minOrderText, STEPS } from "./landing";
import type { Pricing } from "./pricing";

const pricing: Pricing = {
  currency: "RUB",
  min_order: 500,
  margin: 0.35,
  k_supports: 1.15,
  materials: {
    PLA: { price_per_g: 4, tech: "FDM" },
    PETG: { price_per_g: 4.5, tech: "FDM" },
    NYLON: { price_per_g: 9, tech: "FDM" },
  },
  technologies: { FDM: { machine_rate: 120 } },
  batch: [{ from: 1, k: 1 }],
  postprocess: { none: 0 },
  delivery: { pickup: 0 },
};

describe("materialCards", () => {
  it("берёт материалы из прайса и подставляет цену за грамм", () => {
    const cards = materialCards(pricing);
    expect(cards.map((c) => c.name)).toEqual(["PLA", "PETG", "NYLON"]);
    expect(cards[0].price).toBe("от 4 ₽/г");
    expect(cards[1].price).toBe("от 4,5 ₽/г");
    expect(cards[0].tagline).not.toBe("");
  });
  it("незнакомый материал из yaml получает общее описание, но цену — свою", () => {
    const nylon = materialCards(pricing)[2];
    expect(nylon.price).toBe("от 9 ₽/г");
    expect(nylon.text.length).toBeGreaterThan(0);
  });
  it("без прайса (API недоступен) — карточки известных материалов без цен", () => {
    const cards = materialCards(null);
    expect(cards.map((c) => c.name)).toEqual(["PLA", "PETG", "ABS"]);
    expect(cards.every((c) => c.price === null)).toBe(true);
  });
});

describe("formatPerGram", () => {
  it("целое без дробной части, дробь через запятую", () => {
    expect(formatPerGram(4)).toBe("4 ₽");
    expect(formatPerGram(4.5)).toBe("4,5 ₽");
    expect(formatPerGram(4.567)).toBe("4,57 ₽");
  });
});

describe("minOrderText", () => {
  it("подставляет минимальный заказ из прайса", () => {
    expect(minOrderText(pricing)).toBe("Минимальный заказ — 500 ₽");
  });
  it("без прайса или с нулём — ничего", () => {
    expect(minOrderText(null)).toBeNull();
    expect(minOrderText({ ...pricing, min_order: 0 })).toBeNull();
  });
});

describe("тексты блоков", () => {
  it("четыре шага и четыре преимущества, все с заголовком и текстом", () => {
    expect(STEPS).toHaveLength(4);
    expect(BENEFITS).toHaveLength(4);
    for (const item of [...STEPS, ...BENEFITS]) {
      expect(item.title.trim()).not.toBe("");
      expect(item.text.trim()).not.toBe("");
    }
  });
});
