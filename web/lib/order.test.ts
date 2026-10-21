import { describe, expect, it } from "vitest";
import {
  EMPTY_FORM,
  formatDate,
  formatPhone,
  isValidEmail,
  isValidPhone,
  needsAddress,
  STATUS_LABELS,
  STATUS_STEPS,
  toRequest,
  validateForm,
} from "./order";

describe("isValidPhone", () => {
  it("принимает российские номера в любом написании", () => {
    expect(isValidPhone("+7 999 123-45-67")).toBe(true);
    expect(isValidPhone("8 (999) 123 45 67")).toBe(true);
    expect(isValidPhone("9991234567")).toBe(true);
  });
  it("принимает иностранный номер с «+»", () => {
    expect(isValidPhone("+375 29 123 45 67")).toBe(true);
  });
  it("отклоняет короткие и буквы", () => {
    expect(isValidPhone("")).toBe(false);
    expect(isValidPhone("123")).toBe(false);
    expect(isValidPhone("abc")).toBe(false);
    expect(isValidPhone("1234567890123456")).toBe(false);
  });
});

describe("isValidEmail", () => {
  it("простая проверка", () => {
    expect(isValidEmail("a@b.ru")).toBe(true);
    expect(isValidEmail(" a@b.ru ")).toBe(true);
    expect(isValidEmail("a@b")).toBe(false);
    expect(isValidEmail("не почта")).toBe(false);
  });
});

describe("validateForm", () => {
  const good = { ...EMPTY_FORM, name: "Иван", phone: "+79991234567", consent: true };

  it("пустая форма — ошибки по всем обязательным полям", () => {
    const e = validateForm(EMPTY_FORM, "pickup");
    expect(Object.keys(e).sort()).toEqual(["consent", "name", "phone"]);
  });
  it("самовывоз: адрес не нужен", () => {
    expect(validateForm(good, "pickup")).toEqual({});
    expect(needsAddress("pickup")).toBe(false);
  });
  it("курьер: адрес обязателен", () => {
    expect(needsAddress("courier_moscow")).toBe(true);
    expect(validateForm(good, "courier_moscow")).toEqual({ address: "Куда доставить?" });
    expect(validateForm({ ...good, address: "Тверская, 1" }, "courier_moscow")).toEqual({});
  });
  it("e-mail не обязателен, но если есть — должен быть похож на e-mail", () => {
    expect(validateForm({ ...good, email: "" }, "pickup")).toEqual({});
    expect(validateForm({ ...good, email: "плохо" }, "pickup")).toEqual({ email: "Проверьте e-mail." });
  });
});

describe("toRequest", () => {
  it("обрезает пробелы, пустые поля → null", () => {
    const body = toRequest(
      { name: " Иван ", phone: " 8 999 1234567 ", email: " ", address: "", comment: " срочно ", consent: true },
      "q-1",
    );
    expect(body).toEqual({
      quote_id: "q-1",
      name: "Иван",
      phone: "8 999 1234567",
      email: null,
      address: null,
      comment: "срочно",
      consent: true,
    });
  });
});

describe("статусы", () => {
  it("у каждого шага есть подпись", () => {
    for (const s of STATUS_STEPS) expect(STATUS_LABELS[s]).toBeTruthy();
    expect(STATUS_STEPS[0]).toBe("new");
  });
});

describe("formatPhone", () => {
  it("российский номер — с пробелами и дефисами", () => {
    expect(formatPhone("+79991234567")).toBe("+7 999 123-45-67");
  });
  it("иностранный — как есть", () => {
    expect(formatPhone("+375291234567")).toBe("+375291234567");
  });
});

describe("formatDate", () => {
  it("показывает московское время", () => {
    expect(formatDate("2026-10-19T20:40:00+00:00")).toBe("19.10.2026, 23:40");
  });
  it("непонятную строку возвращает как есть", () => {
    expect(formatDate("вчера")).toBe("вчера");
  });
});
