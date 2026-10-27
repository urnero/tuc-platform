/** Расчёт печати (B04): типы ответа API и форматирование времени/граммов. */

export type SliceStatus = "queued" | "running" | "done" | "error";

export type SliceResult = {
  material: string;
  supports: boolean;
  print_time_s: number;
  print_time_h: number;
  filament_g: number;
  filament_mm: number;
  layer_height_mm: number | null;
  slicer_version: string;
};

export type SliceRecord = {
  upload_id: string;
  key: string;
  material: string;
  supports: boolean;
  /** Единицы модели (mm | inch), для которых посчитано; после смены единиц запись устаревает. */
  units?: string;
  status: SliceStatus;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  result: SliceResult | null;
};

export const MATERIAL_LABELS: Record<string, string> = {
  PLA: "PLA — базовый, для декора и прототипов",
  PETG: "PETG — прочнее, для функциональных деталей",
  ABS: "ABS — термостойкий, для техники",
};

/** 3723 → «1 ч 2 мин»; 45 → «1 мин» (меньше минуты округляем вверх); 2 дня → «2 д 3 ч». */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.ceil((total % 3600) / 60);
  if (days > 0) return hours > 0 ? `${days} д ${hours} ч` : `${days} д`;
  if (hours > 0) return minutes > 0 && minutes < 60 ? `${hours} ч ${minutes} мин` : `${hours + (minutes === 60 ? 1 : 0)} ч`;
  return `${Math.max(1, minutes)} мин`;
}

/** 8.89 → «8,9 г»; 123.4 → «123 г». */
export function formatGrams(g: number): string {
  const text = g < 10 ? g.toFixed(1) : Math.round(g).toString();
  return `${text.replace(".", ",")} г`;
}

export const STATUS_TEXT: Record<SliceStatus, string> = {
  queued: "В очереди…",
  running: "Считаем печать…",
  done: "Готово",
  error: "Не удалось посчитать",
};

/**
 * Подсказка «когда какой материал» (B42) — показывается под выбором материала.
 * Материалы, которых нет в прайсе, просто не появятся в списке (список приходит из API).
 */
export const MATERIAL_HINTS: Record<string, string> = {
  PLA: "Для фигурок, макетов, декора и прототипов. Самый доступный, ровная поверхность. Боится жары: размягчается от 55 °C (машина летом, батарея).",
  PETG: "Для деталей, которые работают: крепления, корпуса, кухня и улица. Прочнее и гибче PLA, не боится воды, держит до 70 °C.",
  ABS: "Для техники и авто: держит до 90–100 °C, можно шлифовать и склеивать. Детали чуть менее точные, чем из PLA.",
  ASA: "Как ABS, но для улицы: не выцветает на солнце и не боится мороза.",
  TPU: "Гибкий, как резина: прокладки, чехлы, амортизаторы, ремешки.",
  PA: "Нейлон: износостойкий и прочный — шестерни, втулки, петли.",
  PC: "Поликарбонат: самый прочный и термостойкий из обычных (до 110 °C).",
  "PETG-CF": "PETG с углеволокном: жёсткий, матовый, точно держит размеры — кронштейны и корпуса.",
  "PA-CF": "Нейлон с углеволокном: инженерный, для нагруженных деталей вместо металла.",
};

export type StepState = "done" | "active" | "todo";
export type ProgressStep = { label: string; state: StepState };

/**
 * Шаги расчёта для индикатора на странице модели (B42):
 * файл принят → очередь → нарезка слоёв → цена.
 * `hasQuote` — цена уже получена (тогда все шаги пройдены).
 */
export function sliceSteps(status: SliceStatus | null, hasQuote: boolean): ProgressStep[] {
  const labels = ["Модель принята", "Очередь на расчёт", "Нарезаем на слои", "Считаем цену"];
  // Номер текущего шага: 0 — ничего не запускали, 4 — всё готово.
  let current = 1;
  if (status === "queued") current = 1;
  else if (status === "running") current = 2;
  else if (status === "done") current = hasQuote ? 4 : 3;
  const failed = status === "error";
  return labels.map((label, i) => {
    if (i === 0) return { label, state: "done" };
    if (failed) return { label, state: i < 2 ? "done" : i === 2 ? "active" : "todo" };
    return { label, state: i < current ? "done" : i === current ? "active" : "todo" };
  });
}

/** Секунды ожидания → «12 с» / «1 мин 5 с» для строки «идёт …». */
export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s} с`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return rest ? `${m} мин ${rest} с` : `${m} мин`;
}
