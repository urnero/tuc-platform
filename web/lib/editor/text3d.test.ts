import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { FontLoader } from "three/examples/jsm/loaders/FontLoader.js";
import { buildTextGeometry, PINCH_MAX_MM, pinchSize, SINK_MM, textBoxMm, typefaceUrl } from "./text3d";

function loadFont(url: string) {
  const json = JSON.parse(readFileSync(join(__dirname, "../../public", url), "utf-8"));
  return new FontLoader().parse(json);
}

describe("typefaceUrl", () => {
  it("каждому шрифту панели — свой файл, и он лежит в public", () => {
    expect(typefaceUrl("sans", true)).toBe("/fonts/typeface/liberation-sans-bold.json");
    expect(typefaceUrl("serif", false)).toBe("/fonts/typeface/liberation-serif-regular.json");
    expect(typefaceUrl("mono", false)).toBe("/fonts/typeface/liberation-mono-regular.json");
    for (const f of ["sans", "serif", "mono"] as const)
      for (const b of [true, false]) expect(() => loadFont(typefaceUrl(f, b))).not.toThrow();
  });
});

describe("buildTextGeometry", () => {
  const font = loadFont(typefaceUrl("sans", false));

  it("кириллица есть, а у «О» внутри дырка (контуры в правильную сторону)", () => {
    const shapes = font.generateShapes("О", 10);
    expect(shapes).toHaveLength(1);
    expect(shapes[0].holes).toHaveLength(1);
  });

  it("надпись по центру, буквы примерно size мм, выпукло — наружу", () => {
    const geo = buildTextGeometry(font, "ТУЦ", 10, 1, "raised")!;
    const b = geo.boundingBox!;
    expect((b.min.x + b.max.x) / 2).toBeCloseTo(0, 6);
    expect((b.min.y + b.max.y) / 2).toBeCloseTo(0, 6);
    // Заглавные Liberation Sans ≈ 0,69 em, em = size / 0,72 → ≈ 9,5 мм.
    const caps = textBoxMm(buildTextGeometry(font, "НТ", 10, 1, "raised")!).height;
    expect(caps).toBeGreaterThan(8.5);
    expect(caps).toBeLessThan(10.5);
    expect(textBoxMm(geo).width).toBeGreaterThan(20);
    expect(b.min.z).toBeCloseTo(-SINK_MM, 6);
    expect(b.max.z).toBeCloseTo(1 - SINK_MM, 6);
  });

  it("врезано — внутрь модели; длиннее текст — шире; пустой — null", () => {
    const geo = buildTextGeometry(font, "ТУЦ", 10, 2, "engraved")!;
    expect(geo.boundingBox!.max.z).toBeCloseTo(SINK_MM, 6);
    expect(geo.boundingBox!.min.z).toBeCloseTo(-2 + SINK_MM, 6);
    const longer = buildTextGeometry(font, "ТУЦ ТУЦ", 10, 2, "engraved")!;
    expect(textBoxMm(longer).width).toBeGreaterThan(textBoxMm(geo).width * 1.8);
    expect(buildTextGeometry(font, "   ", 10, 1, "raised")).toBeNull();
  });
});

describe("pinchSize", () => {
  it("растёт и уменьшается вместе с расстоянием между пальцами", () => {
    expect(pinchSize(10, 100, 200)).toBe(20);
    expect(pinchSize(10, 100, 50)).toBe(5);
    expect(pinchSize(10, 100, 133)).toBe(13.5);
  });
  it("в пределах сервера и не ломается на нуле", () => {
    expect(pinchSize(10, 100, 1)).toBe(3);
    expect(pinchSize(50, 100, 1000)).toBe(PINCH_MAX_MM);
    expect(pinchSize(10, 0, 100)).toBe(10);
  });
});
