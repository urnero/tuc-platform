/**
 * Живой 3D-логотип в окне редактора (B62, docs/EDITOR.md).
 *
 * Логотип — только SVG (решение в DECISIONS 2026-11-03): контуры из файла выдавливаются
 * на глубину, как это потом сделает OpenSCAD на сервере (`resize([size_mm, 0]) import(…)`):
 * ширина логотипа = size_mm, пропорции сохраняются, центр — в точке размещения.
 *
 * Система координат — та же, что у надписи (text3d.ts): X — вправо, Y — «верх» логотипа,
 * Z — наружу из поверхности. В SVG ось Y смотрит вниз, поэтому её переворачиваем.
 *
 * Разбор SVG (`parseLogoSvg`) работает только в браузере (нужен DOMParser);
 * геометрию (`buildLogoGeometry`) можно проверить тестами на готовых контурах.
 */

import * as THREE from "three";
import { SVGLoader } from "three/examples/jsm/loaders/SVGLoader.js";
import type { EmbossStyle } from "../emboss";
import { SINK_MM } from "./text3d";

/** Ширина логотипа по умолчанию (мм) — как у старой формы (LOGO_FORM). */
export const LOGO_DEFAULT_MM = 20;

/**
 * Текст SVG → контуры для выдавливания. Пути без заливки (`fill="none"`) пропускаем —
 * это обводки, их сервер не рисует; если заливки нет совсем — берём всё, что есть.
 */
export function parseLogoSvg(svgText: string): THREE.ShapePath[] {
  const { paths } = new SVGLoader().parse(svgText);
  const filled = paths.filter((p) => {
    const fill = (p.userData?.style as { fill?: string } | undefined)?.fill;
    return fill !== "none" && fill !== "transparent";
  });
  return filled.length ? filled : paths;
}

/** Контуры → фигуры three.js (дырки в буквах «О», «А» — отверстия внутри фигуры). */
export function logoShapes(paths: THREE.ShapePath[]): THREE.Shape[] {
  return paths.flatMap((p) => p.toShapes());
}

/** Соотношение сторон логотипа (ширина / высота); 1 — если контуров нет. */
export function logoAspect(shapes: THREE.Shape[]): number {
  const box = shapesBox(shapes);
  if (!box) return 1;
  const w = box.max.x - box.min.x;
  const h = box.max.y - box.min.y;
  return w > 0 && h > 0 ? w / h : 1;
}

function shapesBox(shapes: THREE.Shape[]): THREE.Box2 | null {
  const box = new THREE.Box2();
  for (const s of shapes) for (const p of s.getPoints(4)) box.expandByPoint(p);
  return box.isEmpty() ? null : box;
}

/**
 * 3D-геометрия логотипа: ширина widthMm, высота по пропорциям, выдавлен на depthMm.
 * Выпукло — от поверхности наружу (Z 0…depth), врезано — внутрь (Z −depth…0), как у надписи.
 * Нет контуров → null (окно покажет плашку).
 */
export function buildLogoGeometry(
  shapes: THREE.Shape[],
  widthMm: number,
  depthMm: number,
  mode: EmbossStyle,
): THREE.BufferGeometry | null {
  const box = shapesBox(shapes);
  if (!box) return null;
  const w = box.max.x - box.min.x;
  if (!(w > 0)) return null;
  const k = widthMm / w;
  const geo = new THREE.ExtrudeGeometry(shapes, { depth: depthMm / k, curveSegments: 6, bevelEnabled: false });
  const cx = (box.min.x + box.max.x) / 2;
  const cy = (box.min.y + box.max.y) / 2;
  geo.translate(-cx, -cy, 0);
  // Масштаб до ширины и переворот Y (в SVG ось вниз). Переворот выворачивает треугольники —
  // поэтому переворачиваем и Z, а потом возвращаем выдавливание наружу (Z 0…depth).
  geo.scale(k, -k, -k);
  geo.translate(0, 0, depthMm);
  const z0 = mode === "engraved" ? -depthMm + SINK_MM : -SINK_MM;
  geo.translate(0, 0, z0);
  geo.computeVertexNormals();
  geo.computeBoundingBox();
  return geo;
}
