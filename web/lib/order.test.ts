import { describe, expect, it } from "vitest";
import {
  EMPTY_FORM,
  formatDate,
  formatPhone,
  innKind,
  isValidEmail,
  isValidKpp,
  isValidPhone,
  needsAddress,
  notificationsBlock,
  paysByInvoice,
  prefillForm,
  quoteLoadError,
  STATUS_LABELS,
  STATUS_STEPS,
  toRequest,
  uploadIdFromQuote,
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
      { ...EMPTY_FORM, name: " Иван ", phone: " 8 999 1234567 ", email: " ", address: "", comment: " срочно ", consent: true },
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
      company: null,
    });
  });
  it("заказ от организации (B33): блок company, ИНН без пробелов, КПП только у организаций", () => {
    const org = { ...EMPTY_FORM, b2b: true, companyName: " ООО «Ромашка» ", inn: "77 070 83893", kpp: " 770101001 ", companyAddress: "" };
    expect(toRequest(org, "q-1").company).toEqual({ name: "ООО «Ромашка»", inn: "7707083893", kpp: "770101001", address: null });
    const ip = { ...org, companyName: "ИП Иванов", inn: "500100732259" };
    expect(toRequest(ip, "q-1").company).toEqual({ name: "ИП Иванов", inn: "500100732259", kpp: null, address: null });
    expect(toRequest({ ...org, b2b: false }, "q-1").company).toBeNull();
  });
});

describe("B2B (B33)", () => {
  const good = { ...EMPTY_FORM, name: "Иван", phone: "+79991234567", consent: true, email: "buh@romashka.ru" };

  it("innKind: контрольные цифры как у ФНС", () => {
    expect(innKind("7707083893")).toBe("org");
    expect(innKind("77 070 83893")).toBe("org");
    expect(innKind("500100732259")).toBe("ip");
    expect(innKind("7707083894")).toBeNull();
    expect(innKind("500100732258")).toBeNull();
    expect(innKind("123")).toBeNull();
    expect(innKind("77070838931")).toBeNull();
    expect(innKind("")).toBeNull();
  });
  it("isValidKpp", () => {
    expect(isValidKpp("770101001")).toBe(true);
    expect(isValidKpp("7701AB001")).toBe(true);
    expect(isValidKpp("77010100")).toBe(false);
  });
  it("галочка «от организации» требует наименование, ИНН и e-mail", () => {
    const e = validateForm({ ...good, b2b: true, email: "" }, "pickup");
    expect(Object.keys(e).sort()).toEqual(["companyName", "email", "inn"]);
  });
  it("правильные реквизиты организации проходят, плохой КПП — нет, у ИП КПП не проверяется", () => {
    const org = { ...good, b2b: true, companyName: "ООО «Ромашка»", inn: "7707083893" };
    expect(validateForm(org, "pickup")).toEqual({});
    expect(validateForm({ ...org, kpp: "12" }, "pickup")).toEqual({ kpp: "КПП — 9 знаков, например 770101001." });
    expect(validateForm({ ...org, inn: "500100732259", kpp: "12" }, "pickup")).toEqual({});
  });
  it("paysByInvoice: у старых ответов API поля нет → онлайн", () => {
    expect(paysByInvoice({ payment_method: "invoice" })).toBe(true);
    expect(paysByInvoice({ payment_method: "online" })).toBe(false);
    expect(paysByInvoice({})).toBe(false);
  });
});

describe("статусы", () => {
  it("у каждого шага есть подпись", () => {
    for (const s of STATUS_STEPS) expect(STATUS_LABELS[s]).toBeTruthy();
    expect(STATUS_STEPS[0]).toBe("new");
  });
});

describe("notificationsBlock (B34)", () => {
  const link = "https://t.me/tuc_bot?start=abc";
  it("e-mail и Telegram — одной фразой, ссылка на бота — пока он не подключён", () => {
    const n = { email: "a@b.ru", telegram_linked: false, telegram_link: link };
    expect(notificationsBlock({ status: "new", notifications: n })).toEqual({
      text: "Когда статус изменится, напишем на e-mail a@b.ru.",
      telegramLink: link,
    });
    const both = { email: "a@b.ru", telegram_linked: true, telegram_link: null };
    expect(notificationsBlock({ status: "printing", notifications: both })).toEqual({
      text: "Когда статус изменится, напишем на e-mail a@b.ru и в Telegram.",
      telegramLink: null,
    });
  });
  it("без каналов — зовём подключить Telegram или следить за страницей", () => {
    const only = { email: null, telegram_linked: false, telegram_link: link };
    expect(notificationsBlock({ status: "paid", notifications: only })?.text).toMatch(/подключите Telegram/);
    const none = { email: null, telegram_linked: false, telegram_link: null };
    expect(notificationsBlock({ status: "paid", notifications: none })).toEqual({
      text: "Следите за статусом на этой странице — она обновляется при каждом открытии.",
      telegramLink: null,
    });
  });
  it("выданный и отменённый заказ, старый ответ API без блока — ничего", () => {
    const n = { email: "a@b.ru", telegram_linked: true, telegram_link: null };
    expect(notificationsBlock({ status: "done", notifications: n })).toBeNull();
    expect(notificationsBlock({ status: "cancelled", notifications: n })).toBeNull();
    expect(notificationsBlock({ status: "new" })).toBeNull();
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

describe("uploadIdFromQuote", () => {
  it("достаёт id загрузки из id расчёта", () => {
    expect(uploadIdFromQuote("0123456789abcdef0123456789abcdef-a1b2c3")).toBe("0123456789abcdef0123456789abcdef");
  });
  it("возвращает null для мусора", () => {
    expect(uploadIdFromQuote("")).toBeNull();
    expect(uploadIdFromQuote("../etc/passwd")).toBeNull();
    expect(uploadIdFromQuote("0123456789abcdef0123456789abcdef")).toBeNull();
  });
});

describe("quoteLoadError", () => {
  it("объясняет 404 и 410, остальное — кодом", () => {
    expect(quoteLoadError(404)).toContain("не найден");
    expect(quoteLoadError(410)).toContain("устарел");
    expect(quoteLoadError(500)).toBe("Ошибка 500.");
  });
});

describe("prefillForm", () => {
  const account = {
    email: "ivan@example.ru",
    contacts: { name: "Иван", phone: "+79991234567", address: "Москва, Тверская 1" },
  };
  it("заполняет пустые поля из кабинета", () => {
    expect(prefillForm(EMPTY_FORM, account)).toEqual({
      ...EMPTY_FORM,
      name: "Иван",
      phone: "+79991234567",
      email: "ivan@example.ru",
      address: "Москва, Тверская 1",
    });
  });
  it("не трогает то, что клиент уже ввёл", () => {
    const typed = { ...EMPTY_FORM, name: "Пётр", email: "p@example.ru" };
    const out = prefillForm(typed, account);
    expect(out.name).toBe("Пётр");
    expect(out.email).toBe("p@example.ru");
    expect(out.phone).toBe("+79991234567");
  });
  it("без прошлых заказов — только e-mail", () => {
    expect(prefillForm(EMPTY_FORM, { email: "new@example.ru", contacts: null })).toEqual({ ...EMPTY_FORM, email: "new@example.ru" });
  });
});
