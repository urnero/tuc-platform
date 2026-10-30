import { describe, expect, it } from "vitest";
import {
  badgeClass,
  buttonClass,
  cx,
  effectiveTheme,
  nextTheme,
  parseTheme,
  STATUS_TONES,
  statusTone,
  THEME_INIT_SCRIPT,
  THEME_STORAGE_KEY,
} from "./ui";
import { STATUS_LABELS } from "./order";

describe("cx", () => {
  it("склеивает классы и пропускает пустое", () => {
    expect(cx("btn", false, null, undefined, "", "  ", "btn-sm")).toBe("btn btn-sm");
  });
});

describe("buttonClass / badgeClass", () => {
  it("по умолчанию — оранжевая кнопка обычного размера", () => {
    expect(buttonClass()).toBe("btn btn-primary");
  });
  it("вариант, размер и свои классы", () => {
    expect(buttonClass("secondary", "sm", "w-full")).toBe("btn btn-secondary btn-sm w-full");
    expect(buttonClass("ghost")).toBe("btn btn-ghost");
  });
  it("бейдж", () => {
    expect(badgeClass()).toBe("badge badge-neutral");
    expect(badgeClass("success", "ml-2")).toBe("badge badge-success ml-2");
  });
});

describe("statusTone", () => {
  it("у каждого статуса заказа есть тон", () => {
    for (const s of Object.keys(STATUS_LABELS) as Array<keyof typeof STATUS_LABELS>) {
      expect(STATUS_TONES[s]).toBeDefined();
    }
  });
  it("зелёный — только «Готов» и «Выдан», красный — отменённый", () => {
    expect(statusTone("ready")).toBe("success");
    expect(statusTone("done")).toBe("success");
    expect(statusTone("cancelled")).toBe("danger");
    expect(statusTone("new")).toBe("neutral");
    expect(statusTone("printing")).toBe("active");
  });
});

describe("тема", () => {
  it("parseTheme: мусор → system", () => {
    expect(parseTheme("dark")).toBe("dark");
    expect(parseTheme("light")).toBe("light");
    expect(parseTheme("blue")).toBe("system");
    expect(parseTheme(null)).toBe("system");
  });
  it("nextTheme: переключает, из system — против системной", () => {
    expect(nextTheme("light", false)).toBe("dark");
    expect(nextTheme("dark", true)).toBe("light");
    expect(nextTheme("system", true)).toBe("light");
    expect(nextTheme("system", false)).toBe("dark");
  });
  it("effectiveTheme", () => {
    expect(effectiveTheme("system", true)).toBe("dark");
    expect(effectiveTheme("system", false)).toBe("light");
    expect(effectiveTheme("light", true)).toBe("light");
  });
  it("скрипт инициализации читает тот же ключ и ставит data-theme", () => {
    expect(THEME_INIT_SCRIPT).toContain(THEME_STORAGE_KEY);
    expect(THEME_INIT_SCRIPT).toContain('setAttribute("data-theme"');
    expect(THEME_INIT_SCRIPT).toContain("try{");
  });
});
