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
