import { describe, expect, it } from "vitest";
import { isDarkTheme, SCENE_FALLBACK, sceneColors } from "./scene";

describe("sceneColors", () => {
  it("берёт фон и сетку из токенов --surface/--line/--steel", () => {
    const vars: Record<string, string> = { "--surface": " #f5f2ec", "--line": "#d9d3c8", "--steel": "#3e5566" };
    expect(sceneColors(false, (n) => vars[n] ?? "")).toEqual({ background: "#f5f2ec", cell: "#d9d3c8", section: "#3e5566" });
  });

  it("без CSS — запасные цвета своей темы, светлая не тёмная", () => {
    expect(sceneColors(false)).toEqual(SCENE_FALLBACK.light);
    expect(sceneColors(true)).toEqual(SCENE_FALLBACK.dark);
    expect(SCENE_FALLBACK.light.background).not.toBe("#1a2220");
  });
});

describe("isDarkTheme", () => {
  it("data-theme важнее системной настройки", () => {
    expect(isDarkTheme("light", true)).toBe(false);
    expect(isDarkTheme("dark", false)).toBe(true);
  });
  it("без атрибута — как в системе", () => {
    expect(isDarkTheme(null, true)).toBe(true);
    expect(isDarkTheme(null, false)).toBe(false);
  });
});
