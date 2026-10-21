import { describe, expect, it } from "vitest";
import {
  COMPANY,
  formatDocumentsDate,
  LEGAL_NAME_PLACEHOLDER,
  missingRequisites,
  phoneUrl,
  PLACEHOLDER,
  REQUIRED_FIELDS,
  requisite,
  telegramUrl,
} from "./company";

const filled = {
  ...COMPANY,
  legalName: "ИП Иванов Иван Иванович",
  inn: "771234567890",
  legalAddress: "101000, Москва, ул. Примерная, д. 1",
  email: "hi@example.ru",
};

describe("requisite", () => {
  it("возвращает значение, если поле заполнено", () => {
    expect(requisite("legalName", filled)).toBe("ИП Иванов Иван Иванович");
    expect(requisite("brand")).toBe("ТУЦ");
  });
  it("пустое поле или пробелы → заглушка «уточняется»", () => {
    expect(requisite("inn", { ...filled, inn: "" })).toBe(PLACEHOLDER);
    expect(requisite("inn", { ...filled, inn: "   " })).toBe(PLACEHOLDER);
  });
  it("пустое наименование исполнителя → читаемая заглушка для текста оферты", () => {
    expect(requisite("legalName", { ...filled, legalName: "" })).toBe(LEGAL_NAME_PLACEHOLDER);
  });
});

describe("missingRequisites", () => {
  it("в репозитории обязательные реквизиты пусты — предупреждение перечисляет их по-русски", () => {
    expect(missingRequisites(COMPANY)).toEqual(["наименование исполнителя", "ИНН", "адрес", "e-mail"]);
    expect(REQUIRED_FIELDS).toHaveLength(4);
  });
  it("когда всё заполнено — пусто", () => {
    expect(missingRequisites(filled)).toEqual([]);
  });
  it("ОГРНИП и телефон не обязательны (самозанятому ОГРНИП не нужен)", () => {
    expect(missingRequisites({ ...filled, ogrnip: "", phone: "" })).toEqual([]);
  });
});

describe("formatDocumentsDate", () => {
  it("ГГГГ-ММ-ДД → русская дата", () => {
    expect(formatDocumentsDate("2026-10-21")).toBe("21 октября 2026 г.");
    expect(formatDocumentsDate("2027-01-05")).toBe("5 января 2027 г.");
  });
  it("непонятную строку возвращает как есть", () => {
    expect(formatDocumentsDate("скоро")).toBe("скоро");
  });
  it("дата документов в репозитории записана в нужном формате", () => {
    expect(COMPANY.documentsDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("ссылки на контакты", () => {
  it("telegram: ник с @ и без — одна ссылка, пусто → null", () => {
    expect(telegramUrl("tuc_print")).toBe("https://t.me/tuc_print");
    expect(telegramUrl("@tuc_print")).toBe("https://t.me/tuc_print");
    expect(telegramUrl("")).toBeNull();
  });
  it("phone: оставляет только цифры и плюс, пусто → null", () => {
    expect(phoneUrl("+7 999 123-45-67")).toBe("tel:+79991234567");
    expect(phoneUrl("")).toBeNull();
  });
});
