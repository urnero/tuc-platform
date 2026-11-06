import { describe, expect, it } from "vitest";
import { batchHint, clientPerGram, DELIVERY_LABELS, optionLabel, POSTPROCESS_LABELS, quoteLines, type Pricing, type Quote } from "./pricing";

const base: Quote = {
  id: "a-b",
  upload_id: "a",
  created_at: "2026-10-19T20:00:00+00:00",
  currency: "RUB",
  material: "PLA",
  tech: "FDM",
  supports: false,
  qty: 1,
  postprocess: "none",
  delivery: "pickup",
  material_g: 50,
  print_time_s: 7200,
  price_per_g: 4,
  machine_rate: 120,
  k_supports: 1,
  k_batch: 1,
  margin: 0.35,
  min_order: 500,
  material_cost: 200,
  machine_cost: 240,
  unit_price: 594,
  print_subtotal: 594,
  min_order_applied: false,
  postprocess_cost: 0,
  delivery_cost: 0,
  total: 594,
};

describe("optionLabel", () => {
  it("бесплатный вариант — без цены", () => {
    expect(optionLabel(DELIVERY_LABELS, "pickup", 0, false)).toBe("Самовывоз (Москва)");
  });
  it("платный за заказ", () => {
    expect(optionLabel(DELIVERY_LABELS, "courier_moscow", 400, false)).toBe("Курьер по Москве (+400 ₽)");
  });
  it("платный за штуку", () => {
    expect(optionLabel(POSTPROCESS_LABELS, "sanding", 150, true)).toBe("Шлифовка (+150 ₽/шт)");
  });
  it("цена грамма для клиента — с наценкой", () => {
    const p = { margin: 0.4, materials: { PLA: { price_per_g: 2.3, tech: "FDM" } } } as unknown as Pricing;
    expect(clientPerGram(p, "PLA")).toBe(3.2);
    expect(clientPerGram(p, "PA")).toBeNull();
  });
  it("новые варианты B45 подписаны по-русски", () => {
    expect(optionLabel(POSTPROCESS_LABELS, "painting", 900, true)).toBe("Грунт и покраска в один цвет (+900 ₽/шт)");
    expect(optionLabel(DELIVERY_LABELS, "cdek", 500, false)).toBe("СДЭК до пункта выдачи (Россия) (+500 ₽)");
  });
  it("неизвестный ключ показываем как есть", () => {
    expect(optionLabel(POSTPROCESS_LABELS, "paint", 0, true)).toBe("paint");
  });
});

describe("batchHint", () => {
  it("перечисляет ступени со скидкой", () => {
    expect(batchHint([{ from: 1, k: 1 }, { from: 10, k: 0.9 }, { from: 50, k: 0.8 }])).toBe(
      "от 10 шт — −10 %, от 50 шт — −20 %",
    );
  });
  it("без скидок — пусто", () => {
    expect(batchHint([{ from: 1, k: 1 }])).toBe("");
  });
});

describe("quoteLines", () => {
  it("один экземпляр, самовывоз", () => {
    expect(quoteLines(base)).toEqual([
      { label: "Печать одного изделия", value: "594 ₽" },
      { label: "Самовывоз (Москва)", value: "бесплатно" },
    ]);
  });
  it("тираж, скидка, поддержки, шлифовка, курьер", () => {
    const q: Quote = {
      ...base,
      qty: 10,
      supports: true,
      k_supports: 1.15,
      k_batch: 0.9,
      unit_price: 614.79,
      print_subtotal: 6147.9,
      postprocess: "sanding",
      postprocess_cost: 1500,
      delivery: "courier_moscow",
      delivery_cost: 400,
      total: 8048,
    };
    expect(quoteLines(q).map((l) => l.label)).toEqual([
      "Цена за штуку без скидки",
      "Печать × 10 шт",
      "Скидка за тираж −10 %",
      "Печать со скидкой (614,79 ₽ за шт)",
      "Поддержки",
      "Шлифовка × 10 шт",
      "Курьер по Москве",
    ]);
    expect(quoteLines(q)[0].value).toBe("683,10 ₽");
    expect(quoteLines(q)[1].value).toBe("6 831 ₽");
    expect(quoteLines(q)[2].value).toBe("−683,10 ₽");
    expect(quoteLines(q)[3].value).toBe("6 147,90 ₽");
    expect(quoteLines(q)[4].value).toBe("×1,15");
    expect(quoteLines(q)[6].value).toBe("400 ₽");
  });
  it("тираж 50 шт −20 %: строки сходятся (UX 05.11, персона 3)", () => {
    const q: Quote = { ...base, qty: 50, k_batch: 0.8, unit_price: 61.72, print_subtotal: 3086, total: 3086 };
    expect(quoteLines(q).slice(0, 4)).toEqual([
      { label: "Цена за штуку без скидки", value: "77,15 ₽" },
      { label: "Печать × 50 шт", value: "3 857,50 ₽" },
      { label: "Скидка за тираж −20 %", value: "−771,50 ₽" },
      { label: "Печать со скидкой (61,72 ₽ за шт)", value: "3 086 ₽" },
    ]);
  });
  it("тираж без скидки: цена за штуку с копейками × тираж = сумма", () => {
    const q: Quote = { ...base, qty: 3, unit_price: 61.72, print_subtotal: 185.16, total: 500, min_order_applied: true };
    expect(quoteLines(q).slice(0, 2)).toEqual([
      { label: "Цена за штуку", value: "61,72 ₽" },
      { label: "Печать × 3 шт", value: "185,16 ₽" },
    ]);
  });
  it("минимальный заказ", () => {
    const q: Quote = { ...base, unit_price: 90, print_subtotal: 90, min_order_applied: true, total: 500 };
    expect(quoteLines(q)).toContainEqual({ label: "Минимальный заказ", value: "500 ₽" });
  });
});
