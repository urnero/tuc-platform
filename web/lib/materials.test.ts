import { describe, expect, it } from "vitest";
import {
  EMPTY_LEAD,
  formatSize,
  leadRequest,
  type MaterialItem,
  materialFacts,
  materialHint,
  materialOptionLabel,
  validateLead,
} from "./materials";

const pc: MaterialItem = {
  key: "PC",
  tech: "FDM",
  name: "PC (поликарбонат)",
  tagline: "самый прочный, до 110 °C",
  hint: "Поликарбонат: самый прочный.",
  pros: [],
  cons: [],
  uses: [],
  colors: ["прозрачный", "чёрный"],
  heat_c: 110,
  needs_enclosure: true,
  max_mm: [256, 256, 256],
  enabled: true,
  on_request: false,
};

describe("справочник материалов", () => {
  it("факты для карточки", () => {
    expect(materialFacts(pc)).toEqual([
      "держит до 110 °C",
      "печать в закрытой камере",
      "деталь до 256 × 256 × 256 мм",
      "цвета: прозрачный, чёрный",
    ]);
    expect(formatSize([218, 123, 200.5])).toBe("218 × 123 × 200,5 мм");
  });
  it("подсказка: из справочника, иначе запасная", () => {
    expect(materialHint("PC", [pc], { PC: "старая" })).toBe(
      "Поликарбонат: самый прочный.",
    );
    expect(materialHint("PLA", [pc], { PLA: "запасная" })).toBe("запасная");
    expect(materialHint("X", undefined, {})).toBe("");
  });
  it("подпись в списке", () => {
    expect(materialOptionLabel("PC", [pc])).toBe(
      "PC (поликарбонат) — самый прочный, до 110 °C",
    );
    expect(materialOptionLabel("RESIN", [pc])).toBe("RESIN");
  });
});

describe("заявка «цена по запросу»", () => {
  it("проверяет имя, телефон и e-mail", () => {
    expect(validateLead(EMPTY_LEAD)).toEqual({
      name: "Как к вам обращаться?",
      phone: "Телефон в формате +7 999 123-45-67.",
    });
    expect(
      validateLead({
        name: "Аня",
        phone: "+7 999 123-45-67",
        email: "плохой",
        comment: "",
      }),
    ).toEqual({
      email: "Проверьте e-mail.",
    });
    expect(
      validateLead({
        name: "Аня",
        phone: "89991234567",
        email: "",
        comment: "",
      }),
    ).toEqual({});
  });
  it("тело запроса без пустых полей", () => {
    expect(
      leadRequest(
        {
          name: " Аня ",
          phone: "+7 999 123-45-67",
          email: " ",
          comment: "серый",
        },
        "RESIN",
        2,
      ),
    ).toEqual({
      material: "RESIN",
      qty: 2,
      name: "Аня",
      phone: "+7 999 123-45-67",
      email: null,
      comment: "серый",
    });
  });
});
