import { describe, expect, it } from "vitest";
import { cleanCode, loginError, ordersCountLabel, parsePreset, repeatHref } from "./account";

const ORDER = {
  upload_id: "a".repeat(32),
  material: "PETG",
  supports: true,
  qty: 3,
  postprocess: "sanding",
  delivery: "courier_moscow",
};

describe("repeatHref / parsePreset", () => {
  it("кладёт параметры заказа в адрес страницы модели и читает их обратно", () => {
    const href = repeatHref(ORDER);
    expect(href.startsWith(`/upload/${ORDER.upload_id}?`)).toBe(true);
    expect(parsePreset(href.split("?")[1])).toEqual({
      material: "PETG",
      supports: true,
      qty: 3,
      postprocess: "sanding",
      delivery: "courier_moscow",
    });
  });
  it("без параметров — не повтор", () => {
    expect(parsePreset("")).toBeNull();
    expect(parsePreset("?qty=2")).toBeNull();
  });
  it("кривой тираж — 1, огромный — не больше 1000, пустые поля — по умолчанию", () => {
    expect(parsePreset("?material=PLA&qty=abc")).toMatchObject({ qty: 1, supports: false, postprocess: "none", delivery: "pickup" });
    expect(parsePreset("?material=PLA&qty=0")?.qty).toBe(1);
    expect(parsePreset("?material=PLA&qty=99999")?.qty).toBe(1000);
  });
});

describe("cleanCode", () => {
  it("оставляет шесть цифр", () => {
    expect(cleanCode(" 123 456 ")).toBe("123456");
    expect(cleanCode("1234567")).toBe("123456");
    expect(cleanCode("abc")).toBe("");
  });
});

describe("loginError", () => {
  it("текст сервера важнее кода", () => {
    expect(loginError(400, "Неверный код.")).toBe("Неверный код.");
  });
  it("свои тексты для 429 и 503", () => {
    expect(loginError(429)).toContain("Подождите");
    expect(loginError(503)).toContain("недоступен");
    expect(loginError(500)).toBe("Ошибка 500.");
  });
});

describe("ordersCountLabel", () => {
  it("склоняет", () => {
    expect(ordersCountLabel(1)).toBe("1 заказ");
    expect(ordersCountLabel(2)).toBe("2 заказа");
    expect(ordersCountLabel(5)).toBe("5 заказов");
    expect(ordersCountLabel(11)).toBe("11 заказов");
    expect(ordersCountLabel(21)).toBe("21 заказ");
    expect(ordersCountLabel(0)).toBe("0 заказов");
  });
});
