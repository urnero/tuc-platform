import { describe, expect, it } from "vitest";
import { fileExt, formatBytes, formatDims, validateFile, warningText } from "./mesh";

describe("fileExt", () => {
  it("приводит к нижнему регистру", () => {
    expect(fileExt("Деталь.STL")).toBe("stl");
  });
  it("без расширения — пустая строка", () => {
    expect(fileExt("model")).toBe("");
  });
});

describe("validateFile", () => {
  it("stl и 3mf проходят", () => {
    expect(validateFile("a.stl", 10)).toBeNull();
    expect(validateFile("a.3MF", 10)).toBeNull();
  });
  it("obj не проходит", () => {
    expect(validateFile("a.obj", 10)).toMatch(/STL и 3MF/);
  });
  it("пустой и слишком большой", () => {
    expect(validateFile("a.stl", 0)).toMatch(/пустой/);
    expect(validateFile("a.stl", 101 * 1024 * 1024)).toMatch(/100 МБ/);
  });
});

describe("formatDims", () => {
  it("целые без десятых, дробные с одной", () => {
    expect(formatDims({ x: 20, y: 30.5, z: 40 })).toBe("20 × 30,5 × 40 мм");
  });
  it("в дюймах — два знака", () => {
    expect(formatDims({ x: 25.4, y: 50.8, z: 30 }, "inch")).toBe("1 × 2 × 1,18″");
  });
});

describe("formatBytes", () => {
  it("байты, КБ, МБ", () => {
    expect(formatBytes(500)).toBe("500 Б");
    expect(formatBytes(1536)).toBe("1,5 КБ");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2,0 МБ");
  });
});

describe("warningText", () => {
  it("известный код → текст, неизвестный → сам код", () => {
    expect(warningText("not_watertight")).toMatch(/не замкнута/);
    expect(warningText("something_new")).toBe("something_new");
  });
});
