import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { buildLogoGeometry, logoAspect, logoShapes } from "./logo3d";
import { SINK_MM } from "./text3d";

/** Квадрат 100×50 в координатах SVG (Y вниз) с квадратной дыркой — как буква «О». */
function frame(): THREE.ShapePath[] {
  const p = new THREE.ShapePath();
  p.moveTo(0, 0);
  p.lineTo(100, 0);
  p.lineTo(100, 50);
  p.lineTo(0, 50);
  p.lineTo(0, 0);
  // Дырка — обход в другую сторону.
  p.moveTo(40, 20);
  p.lineTo(40, 30);
  p.lineTo(60, 30);
  p.lineTo(60, 20);
  p.lineTo(40, 20);
  return [p];
}

describe("logo3d (B62)", () => {
  it("ширина = size_mm, пропорции сохранены, центр в начале координат", () => {
    const shapes = logoShapes(frame());
    expect(logoAspect(shapes)).toBeCloseTo(2);
    const geo = buildLogoGeometry(shapes, 20, 1.5, "raised")!;
    const b = geo.boundingBox!;
    expect(b.max.x - b.min.x).toBeCloseTo(20);
    expect(b.max.y - b.min.y).toBeCloseTo(10);
    expect((b.min.x + b.max.x) / 2).toBeCloseTo(0);
    expect((b.min.y + b.max.y) / 2).toBeCloseTo(0);
  });

  it("выпукло — наружу, врезано — внутрь модели (как у надписи)", () => {
    const shapes = logoShapes(frame());
    const raised = buildLogoGeometry(shapes, 20, 2, "raised")!.boundingBox!;
    expect(raised.min.z).toBeCloseTo(-SINK_MM);
    expect(raised.max.z).toBeCloseTo(2 - SINK_MM);
    const engraved = buildLogoGeometry(shapes, 20, 2, "engraved")!.boundingBox!;
    expect(engraved.min.z).toBeCloseTo(-2 + SINK_MM);
    expect(engraved.max.z).toBeCloseTo(SINK_MM);
  });

  it("дырка остаётся дыркой, нет контуров — null", () => {
    const shapes = logoShapes(frame());
    expect(shapes).toHaveLength(1);
    expect(shapes[0].holes).toHaveLength(1);
    expect(buildLogoGeometry([], 20, 1, "raised")).toBeNull();
    expect(logoAspect([])).toBe(1);
  });

  it("верх SVG — вверх в окне (ось Y перевёрнута)", () => {
    // Треугольник остриём вверх в SVG: острие при y = 0 (верх картинки).
    const p = new THREE.ShapePath();
    p.moveTo(50, 0);
    p.lineTo(100, 100);
    p.lineTo(0, 100);
    p.lineTo(50, 0);
    const geo = buildLogoGeometry(logoShapes([p]), 10, 1, "raised")!;
    const pos = geo.getAttribute("position");
    let topX = 0;
    let topY = -Infinity;
    for (let i = 0; i < pos.count; i++) if (pos.getY(i) > topY) [topX, topY] = [pos.getX(i), pos.getY(i)];
    expect(topX).toBeCloseTo(0); // самая верхняя точка — острие посередине
    expect(topY).toBeCloseTo(5);
  });
});
