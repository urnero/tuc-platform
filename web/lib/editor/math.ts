/**
 * Математика интерактивного редактора (B60, docs/EDITOR.md) — без three.js, чтобы тестировать
 * в vitest. Все векторы — тройки чисел.
 *
 * Две системы координат:
 *  - «модель» — как в файле клиента и в OpenSCAD на сервере: мм, Z вверх. В ней хранится
 *    размещение (placement) и в ней его принимает API.
 *  - «сцена» — three.js: Y вверх. Окно просмотра поворачивает модель на −90° вокруг X
 *    (ModelViewer / EditorCanvas) и сдвигает её так, чтобы она стояла на полу по центру.
 *
 * Та же формула касательной системы — в api/app/emboss.py::tangent_frame: если менять здесь,
 * менять и там.
 */

export type Vec3 = [number, number, number];

/** Размещение наложения на поверхности — ровно то, что уходит в params.placement API. */
export type Placement = {
  /** Точка на поверхности, мм, система модели. */
  point: Vec3;
  /** Нормаль наружу (единичная). */
  normal: Vec3;
  /** Куда смотрит верх букв: единичный, перпендикулярен нормали. */
  up: Vec3;
};

const EPS = 1e-6;

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
export const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
export const length = (a: Vec3): number => Math.sqrt(dot(a, a));

/** Единичный вектор; нулевой остаётся нулевым. */
export function normalize(a: Vec3): Vec3 {
  const l = length(a);
  return l < EPS ? [0, 0, 0] : scale(a, 1 / l);
}

/** Проекция вектора на касательную плоскость с нормалью n (n — единичная). */
export function projectToPlane(v: Vec3, n: Vec3): Vec3 {
  return sub(v, scale(n, dot(v, n)));
}

/**
 * Локальная система тиснения в точке поверхности: right, up, normal — единичные и взаимно
 * перпендикулярные. up — проекция подсказки на касательную плоскость; если подсказка
 * параллельна нормали — «верх» модели (+Z), а на горизонтальной грани — +Y.
 * right = up × normal: текст читается снаружи, а не зеркально.
 */
export function tangentFrame(normal: Vec3, upHint?: Vec3): { right: Vec3; up: Vec3; normal: Vec3 } {
  const n = normalize(normal);
  const hints: Vec3[] = upHint ? [upHint] : [];
  hints.push([0, 0, 1], [0, 1, 0]);
  let up: Vec3 = [0, 1, 0];
  for (const hint of hints) {
    const p = projectToPlane(hint, n);
    if (length(p) > EPS) {
      up = normalize(p);
      break;
    }
  }
  return { right: cross(up, n), up, normal: n };
}

/** Размещение с «причёсанными» нормалью и верхом — такое, каким его примет сервер. */
export function makePlacement(point: Vec3, normal: Vec3, upHint?: Vec3): Placement {
  const f = tangentFrame(normal, upHint);
  return { point, normal: f.normal, up: f.up };
}

/** Поворот вектора v вокруг единичной оси axis на угол angle (радианы, формула Родрига). */
export function rotateAround(v: Vec3, axis: Vec3, angle: number): Vec3 {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const k = normalize(axis);
  return add(add(scale(v, c), scale(cross(k, v), s)), scale(k, dot(k, v) * (1 - c)));
}

/** Повернуть «верх» наложения вокруг нормали на угол (радианы, против часовой, если смотреть снаружи). */
export function rotateUp(p: Placement, angle: number): Placement {
  return makePlacement(p.point, p.normal, rotateAround(p.up, p.normal, angle));
}

/** Угол (радианы) между «верхом» размещения и подсказкой по умолчанию — для ползунка поворота. */
export function upAngle(p: Placement): number {
  const base = tangentFrame(p.normal).up;
  const side = cross(p.normal, base); // куда уходит верх при повороте на +90°
  return Math.atan2(dot(p.up, side), dot(p.up, base));
}

// --- сцена three.js ↔ система модели -----------------------------------------------------

/** Как окно просмотра поставило модель: сдвиг обёртки в сцене (после поворота −90° вокруг X). */
export type SceneFit = { offset: Vec3 };

/** Точка сцены → точка модели (мм, Z вверх). Обратный поворот: (x, y, z) → (x, −z, y). */
export function sceneToModel(p: Vec3, fit: SceneFit): Vec3 {
  const d = sub(p, fit.offset);
  return [d[0], -d[2], d[1]];
}

/** Точка модели → точка сцены. Поворот −90° вокруг X: (x, y, z) → (x, z, −y), плюс сдвиг. */
export function modelToScene(m: Vec3, fit: SceneFit): Vec3 {
  return add([m[0], m[2], -m[1]], fit.offset);
}

/** Направления (нормаль, верх) поворачиваются без сдвига. */
export const sceneDirToModel = (v: Vec3): Vec3 => [v[0], -v[2], v[1]];
export const modelDirToScene = (v: Vec3): Vec3 => [v[0], v[2], -v[1]];

/**
 * Матрица 4×4 (column-major, как Matrix4.fromArray в three.js) из локальной системы
 * размещения: столбцы right, up, normal, точка. Точка и оси — уже в координатах сцены.
 */
export function frameMatrix(point: Vec3, right: Vec3, up: Vec3, normal: Vec3): number[] {
  return [...right, 0, ...up, 0, ...normal, 0, ...point, 1];
}

/** Та же матрица для сцены three.js: размещение из системы модели → базис и точка в сцене. */
export function placementSceneMatrix(p: Placement, fit: SceneFit): number[] {
  const f = tangentFrame(p.normal, p.up);
  return frameMatrix(
    modelToScene(p.point, fit),
    modelDirToScene(f.right),
    modelDirToScene(f.up),
    modelDirToScene(f.normal),
  );
}

/** Округление для отправки на сервер и сравнения размещений: мм до 0,001, направления до 1e-6. */
export function roundPlacement(p: Placement): Placement {
  const r = (v: Vec3, d: number): Vec3 => v.map((x) => Number(x.toFixed(d))) as Vec3;
  return { point: r(p.point, 3), normal: r(p.normal, 6), up: r(p.up, 6) };
}

/** Грубая ширина надписи в мм для плашки-предпросмотра (до живого 3D-текста в B61). */
export function textWidthMm(text: string, sizeMm: number): number {
  const chars = Math.max(1, text.trim().length);
  return Math.max(sizeMm, chars * sizeMm * 0.62);
}
