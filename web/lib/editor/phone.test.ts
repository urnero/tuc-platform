import { describe, expect, it } from "vitest";
import { gizmoHint, gizmoSize, isPhoneWidth, panelHint } from "./phone";

describe("телефон в редакторе (B60b)", () => {
  it("телефон — уже 768 px, как граница md у Tailwind", () => {
    expect(isPhoneWidth(390)).toBe(true);
    expect(isPhoneWidth(767)).toBe(true);
    expect(isPhoneWidth(768)).toBe(false);
    expect(isPhoneWidth(1440)).toBe(false);
  });

  it("на телефоне гизмо крупнее", () => {
    expect(gizmoSize(true)).toBe(1.4);
    expect(gizmoSize(false)).toBe(0.8);
  });

  it("подсказка по режиму гизмо", () => {
    expect(gizmoHint("translate")).toContain("стрелки");
    expect(gizmoHint("rotate")).toContain("повернуть");
    expect(gizmoHint("scale")).toContain("размер");
    expect(gizmoHint("translate", "logo")).toContain("Тяните логотип");
    expect(gizmoHint("scale", "logo")).toContain("на логотипе");
  });
});

describe("подсказка панели надписи (QA 08.11)", () => {
  const base = { kind: "text" as const, selected: false, hasLogo: false, count: 0 };
  it("на телефоне нет «наведите» — только «коснитесь»", () => {
    for (const st of [base, { ...base, count: 2 }, { ...base, selected: true }, { ...base, kind: "logo" as const }]) {
      const t = panelHint({ ...st, phone: true });
      expect(t).not.toMatch(/Наведите|мышью|Нажмите/);
    }
    expect(panelHint({ ...base, phone: true })).toBe("Коснитесь модели — надпись встанет в эту точку и прилипнет к поверхности.");
  });
  it("на десктопе текст прежний", () => {
    expect(panelHint({ ...base, phone: false })).toMatch(/^Наведите на модель и нажмите — надпись/);
    expect(panelHint({ ...base, kind: "logo", phone: false })).toMatch(/^Загрузите SVG-логотип, затем нажмите на модель/);
    expect(panelHint({ ...base, count: 1, phone: false })).toMatch(/^Нажмите на надпись, чтобы изменить, или на свободное место/);
  });
});
