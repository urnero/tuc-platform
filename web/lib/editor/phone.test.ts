import { describe, expect, it } from "vitest";
import { gizmoHint, gizmoSize, isPhoneWidth } from "./phone";

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
  });
});
