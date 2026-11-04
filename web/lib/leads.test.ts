import { describe, expect, it } from "vitest";
import {
  DISMISS_DAYS,
  EMPTY_BRIEF,
  MIN_ENGAGED_MS,
  SENT_DAYS,
  briefFormData,
  callbackRequest,
  exitMemory,
  exitPopupAllowed,
  exitPopupPage,
  isDesktopExit,
  isPhoneReturn,
  parseExitMemory,
  uploadIdFromPath,
  validateBrief,
  validateCallback,
} from "./leads";

const ID = "0123456789abcdef0123456789abcdef";
const DAY = 24 * 60 * 60 * 1000;

describe("выходной попап", () => {
  it("только на страницах выбора модели", () => {
    expect(exitPopupPage("/upload")).toBe(true);
    expect(exitPopupPage(`/upload/${ID}`)).toBe(true);
    expect(exitPopupPage("/catalog/vase")).toBe(true);
    expect(exitPopupPage("/editors")).toBe(true);
    expect(exitPopupPage("/")).toBe(false);
    expect(exitPopupPage("/order/abc")).toBe(false);
    expect(exitPopupPage("/request")).toBe(false);
    expect(exitPopupPage("/uploader")).toBe(false);
  });

  it("не раньше 20 с, один раз за сессию и не после закрытия", () => {
    const base = { path: "/catalog", memory: null, shownThisSession: false, engagedMs: MIN_ENGAGED_MS, now: 1000 };
    expect(exitPopupAllowed(base)).toBe(true);
    expect(exitPopupAllowed({ ...base, engagedMs: 5000 })).toBe(false);
    expect(exitPopupAllowed({ ...base, shownThisSession: true })).toBe(false);
    expect(exitPopupAllowed({ ...base, memory: { until: 2000 } })).toBe(false);
    expect(exitPopupAllowed({ ...base, memory: { until: 500 } })).toBe(true);
    expect(exitPopupAllowed({ ...base, path: "/order/x" })).toBe(false);
  });

  it("память: закрыл — 7 дней, оставил телефон — 30", () => {
    expect(parseExitMemory(exitMemory(0, false))).toEqual({ until: DISMISS_DAYS * DAY });
    expect(parseExitMemory(exitMemory(0, true))).toEqual({ until: SENT_DAYS * DAY });
    expect(parseExitMemory(null)).toBeNull();
    expect(parseExitMemory("{битый")).toBeNull();
    expect(parseExitMemory('{"until":"x"}')).toBeNull();
  });

  it("сигналы ухода", () => {
    expect(isDesktopExit({ clientY: -3, relatedTarget: null })).toBe(true);
    expect(isDesktopExit({ clientY: 200, relatedTarget: null })).toBe(false);
    expect(isDesktopExit({ clientY: 0, relatedTarget: {} })).toBe(false);
    expect(isPhoneReturn(null, 10_000)).toBe(false);
    expect(isPhoneReturn(1000, 3000)).toBe(false);
    expect(isPhoneReturn(1000, 7000)).toBe(true);
  });

  it("заявка «перезвоните»: телефон обязателен, модель из адреса", () => {
    expect(validateCallback({ name: "", phone: "12" }).phone).toBeTruthy();
    expect(validateCallback({ name: "", phone: "+7 999 123-45-67" })).toEqual({});
    expect(uploadIdFromPath(`/upload/${ID}/edit`)).toBe(ID);
    expect(uploadIdFromPath("/upload")).toBeNull();
    expect(callbackRequest({ name: " ", phone: " +7 999 123-45-67 " }, `/upload/${ID}`)).toEqual({
      phone: "+7 999 123-45-67",
      name: null,
      page: `/upload/${ID}`,
      upload_id: ID,
    });
  });
});

describe("заявка без модели", () => {
  const ok = { ...EMPTY_BRIEF, name: "Аня", phone: "89991234567", comment: "Ручка для шкафа" };

  it("проверка полей", () => {
    expect(validateBrief(ok, null)).toEqual({});
    const e = validateBrief({ ...EMPTY_BRIEF, email: "x", qty: "0" }, null);
    expect(Object.keys(e).sort()).toEqual(["comment", "email", "name", "phone", "qty"]);
  });

  it("проверка фото", () => {
    expect(validateBrief(ok, { size: 11 * 1024 * 1024, name: "a.jpg" }).photo).toContain("10 МБ");
    expect(validateBrief(ok, { size: 100, name: "a.pdf" }).photo).toContain("JPG");
    expect(validateBrief(ok, { size: 100, name: "IMG_1.HEIC" })).toEqual({});
  });

  it("form-data для API", () => {
    const photo = new File([new Uint8Array([1, 2])], "p.png", { type: "image/png" });
    const fd = briefFormData({ ...ok, qty: "3", email: "" }, photo, "/request");
    expect(fd.get("name")).toBe("Аня");
    expect(fd.get("qty")).toBe("3");
    expect(fd.get("email")).toBeNull();
    expect(fd.get("page")).toBe("/request");
    expect((fd.get("photo") as File).name).toBe("p.png");
    expect(briefFormData(ok, null, "/request").get("photo")).toBeNull();
  });
});
