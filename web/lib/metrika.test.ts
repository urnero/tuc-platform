import { describe, expect, it } from "vitest";
import { ymId, ymSnippet, reachGoal } from "./metrika";

describe("metrika", () => {
  it("без номера выключена", () => {
    expect(ymId("")).toBeNull();
    expect(ymId(undefined)).toBeNull();
    expect(ymId("abc")).toBeNull();
    expect(ymId("12")).toBeNull();
  });
  it("номер из цифр принимается", () => {
    expect(ymId(" 12345678 ")).toBe("12345678");
  });
  it("код содержит номер и инициализацию", () => {
    const s = ymSnippet("12345678");
    expect(s).toContain('ym(12345678,"init"');
    expect(s).toContain("mc.yandex.ru/metrika/tag.js");
  });
  it("reachGoal без счётчика и без window не падает", () => {
    expect(() => reachGoal("upload")).not.toThrow();
  });
});
