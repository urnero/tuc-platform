import { describe, expect, it } from "vitest";
import { BENEFITS, FACTS, FAQ, faqJsonLd, formatPerGram, materialCards, minOrderText, STEPS, STUDIO } from "./landing";
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
    expect(cards[0].price).toBe("от 5,4 ₽/г");
    expect(cards[1].price).toBe("от 6,1 ₽/г");
    expect(cards[0].tagline).not.toBe("");
  });
  it("незнакомый материал из yaml получает общее описание, но цену — свою", () => {
    const nylon = materialCards(pricing)[2];
    expect(nylon.price).toBe("от 12,2 ₽/г");
    expect(nylon.text.length).toBeGreaterThan(0);
  });
  it("со справочником (B44): названия из yaml, смола — «цена по запросу»", () => {
    const item = (key: string, name: string, on_request: boolean) => ({
      key,
      tech: on_request ? ("SLA" as const) : ("FDM" as const),
      name,
      tagline: "т",
      hint: "х",
      pros: [],
      cons: [],
      uses: [],
      colors: [],
      heat_c: null,
      needs_enclosure: false,
      max_mm: null,
      enabled: true,
      on_request,
    });
    const cards = materialCards(pricing, [item("PETG", "PETG", false), item("RESIN", "Смола", true)]);
    expect(cards.map((c) => [c.name, c.price, c.onRequest])).toEqual([
      ["PETG", "от 6,1 ₽/г", false],
      ["Смола", "цена по запросу", true],
    ]);
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

describe("воронка главной (B41)", () => {
  it("FAQ — от 5 до 7 вопросов, без повторов, у каждого есть ответ", () => {
    expect(FAQ.length).toBeGreaterThanOrEqual(5);
    expect(FAQ.length).toBeLessThanOrEqual(7);
    expect(new Set(FAQ.map((f) => f.q)).size).toBe(FAQ.length);
    for (const f of FAQ) {
      expect(f.q.trim().endsWith("?")).toBe(true);
      expect(f.a.trim().length).toBeGreaterThan(20);
    }
  });

  it("ответ про сроки повторяет обещание из STUDIO — чтобы срок на главной был один", () => {
    const about = FAQ.find((f) => f.q.includes("быстро"));
    expect(about?.a).toContain(STUDIO.leadTime);
  });

  it("факты о парке: четыре плашки с числом и подписью, цифры совпадают с docs/PRINTERS.md", () => {
    expect(FACTS).toHaveLength(4);
    for (const f of FACTS) {
      expect(f.value.trim()).not.toBe("");
      expect(f.label.trim()).not.toBe("");
    }
    expect(FACTS.map((f) => f.value)).toEqual(expect.arrayContaining(["8", "256 мм"]));
  });

  it("faqJsonLd — FAQPage со всеми вопросами, без undefined", () => {
    const ld = faqJsonLd([{ q: "Что?", a: "Это." }]) as { "@type": string; mainEntity: { name: string; acceptedAnswer: { text: string } }[] };
    expect(ld["@type"]).toBe("FAQPage");
    expect(ld.mainEntity).toHaveLength(1);
    expect(ld.mainEntity[0].name).toBe("Что?");
    expect(ld.mainEntity[0].acceptedAnswer.text).toBe("Это.");
    expect(JSON.stringify(faqJsonLd())).not.toContain("undefined");
  });
});
