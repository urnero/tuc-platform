import { describe, expect, it } from "vitest";
import { COMPANY } from "./company";
import {
  EMPTY_LEAD,
  formatSize,
  leadRequest,
  leadSentMessage,
  studioContacts,
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

describe("leadSentMessage", () => {
  it("доставлено владельцу — обещаем ответ в течение дня", () => {
    const m = leadSentMessage(
      { ok: true, telegram: true, delivered: true },
      "+7 999 1",
    );
    expect(m.title).toBe("Заявка отправлена");
    expect(m.text).toContain("+7 999 1");
    expect(m.showContacts).toBe(false);
  });
  it("нет ни бота, ни почты — честный текст и контакты", () => {
    const m = leadSentMessage(
      { ok: true, telegram: false, email: false, delivered: false },
      "x",
    );
    expect(m.title).toBe("Заявка сохранена");
    expect(m.text).not.toContain("в течение рабочего дня");
    expect(m.showContacts).toBe(true);
  });
  it("старый ответ без delivered — по флагу telegram", () => {
    expect(
      leadSentMessage({ ok: true, telegram: false }, "x").showContacts,
    ).toBe(true);
    expect(
      leadSentMessage({ ok: true, telegram: true }, "x").showContacts,
    ).toBe(false);
  });
});

describe("studioContacts", () => {
  const base = { ...COMPANY, phone: "", telegram: "", email: "" };
  it("пустые контакты — пустой список", () => {
    expect(studioContacts(base)).toEqual([]);
  });
  it("только заполненные", () => {
    expect(
      studioContacts({
        ...base,
        phone: "+7 999 123-45-67",
        telegram: "@bro",
        email: "a@b.ru",
      }),
    ).toEqual([
      { label: "+7 999 123-45-67", href: "tel:+79991234567" },
      { label: "Telegram @bro", href: "https://t.me/bro" },
      { label: "a@b.ru", href: "mailto:a@b.ru" },
    ]);
  });
});
