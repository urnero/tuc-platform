/**
 * Раскраска модели по частям (B31): типы ответа API, выбор цветов по умолчанию,
 * проверка формы, подписи, диапазоны треугольников для 3D-просмотра.
 *
 * Сервер: GET /api/v1/paint/colors — палитра; GET /api/v1/uploads/{id}/parts — детали модели
 * (каждая — диапазон треугольников в …/parts/file, STL, где детали лежат подряд);
 * POST /api/v1/uploads/{id}/paints {colors: [код по детали]} → запись сборки
 * (status queued|running|done|error), опрос GET …/paints/{job_id}; после done —
 * result_upload_id = новая загрузка (3MF, каждая деталь своим цветом).
 */

export type PaintColor = { key: string; name: string; hex: string };

export type Part = {
  index: number;
  /** «Деталь 1» … или «Мелкие детали (N шт.)» — хвост, если деталей больше лимита. */
  name: string;
  faces: number;
  /** Первый треугольник детали в parts.stl. */
  first_face: number;
  volume_cm3: number;
  bbox_mm: { x: number; y: number; z: number };
  /** Сколько мелких деталей склеено в эту строку (0 — обычная деталь). */
  merged: number;
};

export type PartsResponse = {
  upload_id: string;
  units: "mm" | "inch";
  triangles: number;
  max_parts: number;
  parts: Part[];
};

export type PaintStatus = "queued" | "running" | "done" | "error";

export type PaintJob = {
  id: string;
  upload_id: string;
  colors: string[];
  status: PaintStatus;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  result_upload_id: string | null;
};

export const STATUS_TEXT: Record<PaintStatus, string> = {
  queued: "В очереди…",
  running: "Собираем…",
  done: "Готово",
  error: "Не получилось",
};

/** Цвета по умолчанию: деталям по кругу раздаём палитру, чтобы разница была видна сразу. */
export function defaultColors(parts: Part[], palette: PaintColor[]): string[] {
  if (palette.length === 0) return parts.map(() => "");
  return parts.map((_, i) => palette[i % palette.length].key);
}

/** Проверка до отправки: каждой детали — цвет из палитры. Текст ошибки или null. */
export function validateColors(colors: string[], parts: Part[], palette: PaintColor[]): string | null {
  if (parts.length === 0) return "В модели нет деталей.";
  if (colors.length !== parts.length) return "Выберите цвет для каждой детали.";
  const keys = new Set(palette.map((c) => c.key));
  const bad = colors.findIndex((c) => !keys.has(c));
  if (bad >= 0) return `Выберите цвет для детали «${parts[bad].name}».`;
  return null;
}

/** Диапазоны треугольников с цветами для 3D-просмотра: [{start, count, hex}]. */
export function partRanges(
  parts: Part[],
  colors: string[],
  palette: PaintColor[],
  fallbackHex = "#4fbfb2",
): { start: number; count: number; hex: string }[] {
  const byKey = new Map(palette.map((c) => [c.key, c.hex]));
  return parts.map((p, i) => ({
    start: p.first_face,
    count: p.faces,
    hex: byKey.get(colors[i] ?? "") ?? fallbackHex,
  }));
}

/** Сколько разных цветов выбрано. */
export function distinctCount(colors: string[]): number {
  return new Set(colors.filter(Boolean)).size;
}

/** Правильная форма слова: 1 деталь, 2 детали, 5 деталей. */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) return few;
  return many;
}

/** «3 детали, 2 цвета» — для заголовка блока. */
export function summaryLine(parts: Part[], colors: string[]): string {
  const n = parts.length;
  const k = distinctCount(colors);
  return `${n} ${plural(n, "деталь", "детали", "деталей")}, ${k} ${plural(k, "цвет", "цвета", "цветов")}`;
}

/** «40 × 30 × 20 мм, 24,0 см³» — подпись детали в списке. */
export function partCaption(p: Part): string {
  const f = (v: number) => String(Number(v.toFixed(1))).replace(".", ",");
  const dims = `${f(p.bbox_mm.x)} × ${f(p.bbox_mm.y)} × ${f(p.bbox_mm.z)} мм`;
  const vol = `${p.volume_cm3.toFixed(1).replace(".", ",")} см³`;
  return p.merged > 0 ? `${vol} вместе` : `${dims}, ${vol}`;
}
