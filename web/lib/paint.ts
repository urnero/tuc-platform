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

// ---------------------------------------------------------------------------
// B63: инструмент «Цвет» — клик по детали в 3D-просмотре, отмена/повтор, счётчик цветов.

/** Сколько цветов принтер печатает за один запуск (AMS / ACE Pro — до 4, docs/PRINTERS.md). */
export const MAX_COLORS_PER_RUN = 4;

/** Какая деталь содержит треугольник faceIndex (номер в parts.stl). -1 — ни одна. */
export function partAtFace(parts: Part[], faceIndex: number | null | undefined): number {
  if (faceIndex === null || faceIndex === undefined || faceIndex < 0) return -1;
  return parts.findIndex((p) => faceIndex >= p.first_face && faceIndex < p.first_face + p.faces);
}

/** Осветлить цвет #rrggbb на долю amount (0…1) — подсветка детали под курсором. */
export function lighten(hex: string, amount = 0.35): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => Math.round(v + (255 - v) * amount));
  return "#" + ch.map((v) => v.toString(16).padStart(2, "0")).join("");
}

/** Предупреждение, если цветов больше, чем принтер берёт за один запуск. Иначе null. */
export function colorsWarning(colors: string[]): string | null {
  const k = distinctCount(colors);
  if (k <= MAX_COLORS_PER_RUN) return null;
  return (
    `${k} ${plural(k, "цвет", "цвета", "цветов")}: за один запуск принтер печатает до ` +
    `${MAX_COLORS_PER_RUN} цветов, поэтому модель напечатаем в несколько заходов — ` +
    `срок может вырасти на день.`
  );
}

/**
 * История раскраски для «Отменить / Повторить» (Ctrl+Z, Ctrl+Shift+Z / Ctrl+Y).
 * present — текущие цвета, past — что было раньше (последнее — ближайшее), future — отменённое.
 */
export type ColorHistory = { past: string[][]; present: string[]; future: string[][] };

/** Сколько шагов назад помним — чтобы история не росла бесконечно. */
export const HISTORY_LIMIT = 100;

export function historyStart(colors: string[]): ColorHistory {
  return { past: [], present: colors, future: [] };
}

/** Новый шаг. Если цвета не изменились — история та же (пустых шагов не бывает). */
export function historyPush(h: ColorHistory, next: string[]): ColorHistory {
  const same = next.length === h.present.length && next.every((v, i) => v === h.present[i]);
  if (same) return h;
  return { past: [...h.past, h.present].slice(-HISTORY_LIMIT), present: next, future: [] };
}

export function historyUndo(h: ColorHistory): ColorHistory {
  if (h.past.length === 0) return h;
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future] };
}

export function historyRedo(h: ColorHistory): ColorHistory {
  if (h.future.length === 0) return h;
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) };
}

/** Какое действие истории просит сочетание клавиш: "undo", "redo" или null. */
export function historyKey(e: { key: string; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }):
  | "undo"
  | "redo"
  | null {
  if (!(e.ctrlKey || e.metaKey)) return null;
  const k = e.key.toLowerCase();
  // «я» и «н» — те же клавиши Z и Y в русской раскладке.
  if (k === "z" || k === "я") return e.shiftKey ? "redo" : "undo";
  if (k === "y" || k === "н") return "redo";
  return null;
}
