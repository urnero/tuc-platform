/**
 * Живой 3D-текст в окне редактора (B61, docs/EDITOR.md).
 *
 * Шрифты — Liberation (как у OpenSCAD на сервере), переведённые в typeface-JSON скриптом
 * web/scripts/make_typefaces.py и лежащие в web/public/fonts/typeface/. Поэтому ширина
 * надписи в окне почти совпадает с тем, что потом вырежет сервер.
 *
 * Система координат надписи — та же, что у плашки B60: X — вправо, Y — «верх» букв,
 * Z — наружу из поверхности; начало — центр надписи на поверхности.
 */

import * as THREE from "three";
import type { Font } from "three/examples/jsm/loaders/FontLoader.js";
import { TextGeometry } from "three/examples/jsm/geometries/TextGeometry.js";
import { LIMITS, type EmbossFont, type EmbossStyle } from "../emboss";

/** Адрес typeface-JSON для шрифта панели (без засечек / с засечками / моноширинный, жирный). */
export function typefaceUrl(font: EmbossFont, bold: boolean): string {
  const family = font === "serif" ? "serif" : font === "mono" ? "mono" : "sans";
  return `/fonts/typeface/liberation-${family}-${bold ? "bold" : "regular"}.json`;
}

/**
 * Насколько надпись утоплена в модель (мм). Выпуклая чуть уходит внутрь, чтобы на изогнутой
 * поверхности под буквами не было щели; вырезанная — чуть торчит, чтобы её было видно.
 */
export const SINK_MM = 0.05;

/**
 * 3D-геометрия надписи: буквы size_mm (как text(size=…) в OpenSCAD), выдавлены на depth_mm,
 * центр надписи — в начале координат (halign/valign = center, как на сервере).
 * Выпукло — от поверхности наружу (Z 0…depth), врезано — внутрь (Z −depth…0).
 * Пустой текст → null (окно покажет плашку).
 */
export function buildTextGeometry(
  font: Font,
  text: string,
  sizeMm: number,
  depthMm: number,
  mode: EmbossStyle,
): THREE.BufferGeometry | null {
  if (!text.trim()) return null;
  const geo = new TextGeometry(text, { font, size: sizeMm, depth: depthMm, curveSegments: 5, bevelEnabled: false });
  geo.computeBoundingBox();
  const box = geo.boundingBox;
  if (!box || box.isEmpty()) {
    geo.dispose();
    return null;
  }
  const cx = (box.min.x + box.max.x) / 2;
  const cy = (box.min.y + box.max.y) / 2;
  const z0 = mode === "engraved" ? -depthMm + SINK_MM : -SINK_MM;
  geo.translate(-cx, -cy, z0);
  geo.computeBoundingBox();
  return geo;
}

/** Ширина и высота надписи по геометрии (мм) — вместо прикидки textWidthMm. */
export function textBoxMm(geo: THREE.BufferGeometry): { width: number; height: number } {
  if (!geo.boundingBox) geo.computeBoundingBox();
  const b = geo.boundingBox!;
  return { width: b.max.x - b.min.x, height: b.max.y - b.min.y };
}

/** Самые крупные буквы, которые можно растянуть щипком / ползунком в редакторе (мм). */
export const PINCH_MAX_MM = 60;

/**
 * Щипок двумя пальцами (телефон): размер букв меняется во столько раз, во сколько
 * изменилось расстояние между пальцами. Округляем до 0,5 мм, держим в пределах сервера.
 */
export function pinchSize(startSizeMm: number, startDistPx: number, distPx: number): number {
  if (!(startDistPx > 0) || !(distPx > 0)) return startSizeMm;
  const raw = (startSizeMm * distPx) / startDistPx;
  const rounded = Math.round(raw * 2) / 2;
  return Math.min(PINCH_MAX_MM, Math.max(LIMITS.size.min, rounded));
}

/** Цвета предпросмотра надписи (только для окна — цвет печати выбирают в «Цвете»). */
export const PREVIEW_COLORS: { value: string; label: string }[] = [
  { value: "#f26a1b", label: "Оранжевый" },
  { value: "#f5f5f0", label: "Белый" },
  { value: "#222222", label: "Чёрный" },
  { value: "#d4af37", label: "Золото" },
  { value: "#2e86de", label: "Синий" },
];
