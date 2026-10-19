import { describe, expect, it } from "vitest";
import { batchHint, DELIVERY_LABELS, optionLabel, POSTPROCESS_LABELS, quoteLines, type Quote } from "./pricing";

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
      "Печать одного изделия",
      "Печать × 10 шт",
      "Скидка за тираж",
      "Поддержки",
      "Шлифовка × 10 шт",
      "Курьер по Москве",
    ]);
    expect(quoteLines(q)[2].value).toBe("−10 %");
    expect(quoteLines(q)[3].value).toBe("×1,15");
    expect(quoteLines(q)[5].value).toBe("400 ₽");
  });
  it("минимальный заказ", () => {
    const q: Quote = { ...base, unit_price: 90, print_subtotal: 90, min_order_applied: true, total: 500 };
    expect(quoteLines(q)).toContainEqual({ label: "Минимальный заказ", value: "500 ₽" });
  });
});
