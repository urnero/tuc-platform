import { describe, expect, it } from "vitest";
import {
  cross,
  dot,
  frameMatrix,
  length,
  makePlacement,
  modelDirToScene,
  modelToScene,
  placementSceneMatrix,
  rotateUp,
  roundPlacement,
  sceneDirToModel,
  sceneToModel,
  tangentFrame,
  textWidthMm,
  transportUp,
  upAngle,
  type Vec3,
} from "./math";

const close = (a: Vec3, b: Vec3, eps = 1e-9) => a.every((v, i) => Math.abs(v - b[i]) < eps);

describe("tangentFrame", () => {
  it("нормаль → normal, проекция подсказки → up, right = up × normal", () => {
    const f = tangentFrame([0, 0, 2], [0, 1, 0]);
    expect(close(f.normal, [0, 0, 1])).toBe(true);
    expect(close(f.up, [0, 1, 0])).toBe(true);
    expect(close(f.right, [1, 0, 0])).toBe(true);
  });

  it("подсказка не в касательной плоскости — проецируется", () => {
    const f = tangentFrame([0, -1, 0], [0, 1, 1]);
    expect(close(f.up, [0, 0, 1])).toBe(true);
    expect(close(f.right, [1, 0, 0])).toBe(true); // текст на передней грани читается слева направо
  });

  it("подсказка параллельна нормали → верх модели; на горизонтали → +Y", () => {
    expect(close(tangentFrame([1, 0, 0], [-1, 0, 0]).up, [0, 0, 1])).toBe(true);
    expect(close(tangentFrame([0, 0, -1], [0, 0, 1]).up, [0, 1, 0])).toBe(true);
    expect(close(tangentFrame([0, 0, 1]).up, [0, 1, 0])).toBe(true);
  });

  it("на наклонной грани базис ортонормированный и правый", () => {
    const n: Vec3 = [1, 1, 1];
    const f = tangentFrame(n, [0, 0, 1]);
    expect(Math.abs(length(f.right) - 1)).toBeLessThan(1e-9);
    expect(Math.abs(length(f.up) - 1)).toBeLessThan(1e-9);
    expect(Math.abs(dot(f.right, f.up))).toBeLessThan(1e-9);
    expect(Math.abs(dot(f.up, f.normal))).toBeLessThan(1e-9);
    expect(close(cross(f.right, f.up), f.normal)).toBe(true);
  });
});

describe("поворот вокруг нормали", () => {
  it("rotateUp на 90° переводит верх в right, upAngle возвращает угол", () => {
    const p = makePlacement([0, 0, 5], [0, 0, 1], [0, 1, 0]);
    const r = rotateUp(p, Math.PI / 2);
    expect(close(r.up, [-1, 0, 0])).toBe(true); // против часовой, если смотреть сверху
    expect(close(r.normal, [0, 0, 1])).toBe(true);
    expect(upAngle(r)).toBeCloseTo(Math.PI / 2, 9);
    expect(upAngle(p)).toBeCloseTo(0, 9);
  });
});

describe("сцена ↔ модель", () => {
  const fit = { offset: [1, 2, 3] as Vec3 };

  it("точка модели (Z вверх) → сцена (Y вверх) и обратно", () => {
    const m: Vec3 = [10, 20, 30];
    const s = modelToScene(m, fit);
    expect(close(s, [11, 32, -17])).toBe(true);
    expect(close(sceneToModel(s, fit), m)).toBe(true);
  });

  it("направления: верх модели +Z — это +Y сцены", () => {
    expect(close(modelDirToScene([0, 0, 1]), [0, 1, 0])).toBe(true);
    expect(close(sceneDirToModel([0, 1, 0]), [0, 0, 1])).toBe(true);
    expect(close(sceneDirToModel(modelDirToScene([3, -4, 5])), [3, -4, 5])).toBe(true);
  });

  it("матрица размещения column-major: столбцы right, up, normal, точка", () => {
    const m = frameMatrix([1, 2, 3], [1, 0, 0], [0, 1, 0], [0, 0, 1]);
    expect(m).toEqual([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 2, 3, 1]);
    // Верхняя грань модели: нормаль +Z модели = +Y сцены, up +Y модели = −Z сцены.
    const sm = placementSceneMatrix(makePlacement([0, 0, 10], [0, 0, 1], [0, 1, 0]), { offset: [0, 0, 0] });
    expect(close(sm.slice(8, 11) as Vec3, [0, 1, 0])).toBe(true);
    expect(close(sm.slice(4, 7) as Vec3, [0, 0, -1])).toBe(true);
    expect(close(sm.slice(12, 15) as Vec3, [0, 10, 0])).toBe(true);
  });
});

describe("мелочи", () => {
  it("roundPlacement округляет мм до 0,001, направления до 1e-6", () => {
    const p = roundPlacement(makePlacement([1.23456, 0, 0], [0, 0, 3], [1, 1, 0]));
    expect(p.point).toEqual([1.235, 0, 0]);
    expect(p.normal).toEqual([0, 0, 1]);
    expect(p.up).toEqual([0.707107, 0.707107, 0]);
  });

  it("textWidthMm растёт с длиной текста, но не меньше размера", () => {
    expect(textWidthMm("", 10)).toBe(10);
    expect(textWidthMm("ТУЦ", 10)).toBeCloseTo(18.6, 6);
  });
});

describe("переход за угол (B60a)", () => {
  it("с передней грани на боковую верх остаётся вверх", () => {
    // Передняя грань куба смотрит в −Y, боковая — в +X; верх букв — +Z.
    const up = transportUp([0, 0, 1], [0, -1, 0], [1, 0, 0]);
    expect(close(up, [0, 0, 1])).toBe(true);
  });

  it("с передней грани на крышку: верх был ровно в новую нормаль — буквы «ложатся» от зрителя", () => {
    const up = transportUp([0, 0, 1], [0, -1, 0], [0, 0, 1]);
    expect(close(up, [0, 1, 0])).toBe(true);
    // Ровно та же система, что при перегибе через ребро: right не меняется.
    const before = tangentFrame([0, -1, 0], [0, 0, 1]);
    const after = tangentFrame([0, 0, 1], up);
    expect(close(before.right, after.right)).toBe(true);
  });

  it("повёрнутый верх сохраняет угол к ребру", () => {
    const s = Math.SQRT1_2;
    const up = transportUp([s, 0, s], [0, -1, 0], [1, 0, 0]);
    // Ребро вдоль Z: составляющая вдоль ребра сохраняется, остальное уходит в новую плоскость.
    expect(close(up, [0, s, s])).toBe(true);
    expect(dot(up, [1, 0, 0])).toBeCloseTo(0, 9);
    expect(length(up)).toBeCloseTo(1, 9);
  });

  it("та же грань или грань напротив — верх как был", () => {
    expect(close(transportUp([0, 0, 1], [0, -1, 0], [0, -1, 0]), [0, 0, 1])).toBe(true);
    expect(close(transportUp([0, 0, 1], [0, -1, 0], [0, 1, 0]), [0, 0, 1])).toBe(true);
  });
});
