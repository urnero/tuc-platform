/**
 * Параметрические редакторы (B21): типы ответа GET /api/v1/editors, загрузчики для страниц
 * /editors и /editors/[slug] и чистые помощники для формы — умолчания, проверка значений
 * (та же логика, что на сервере в api/app/editors.py, чтобы ошибки показывать сразу),
 * подписи. Схема приходит из editors/<slug>/editor.yaml через API; страницы кэшируются
 * на 10 минут (ISR) — владелец правит yaml, сайт подхватывает сам.
 */

import { apiInternalUrl } from "./landing";
import { type MeshInfo } from "./mesh";

export type ParamType = "number" | "bool" | "choice" | "text";

export type EditorParam = {
  name: string;
  label: string;
  type: ParamType;
  default: number | boolean | string;
  hint: string;
  unit: string;
  min: number | null;
  max: number | null;
  step: number | null;
  integer: boolean;
  options: { value: string; label: string }[];
  maxlen: number;
};

export type EditorCheck = { rule: string; message: string };

export type Editor = {
  slug: string;
  title: string;
  text: string;
  /** Материал, который подставится в калькулятор по умолчанию. */
  material: string;
  scad: string;
  order: number;
  params: EditorParam[];
  checks: EditorCheck[];
  /** false — у редактора нет scad-файла; строить нечего, кнопку не показываем. */
  scad_ready: boolean;
};

/** Значения формы: числа и текст держим строками (как в input), галочки — boolean. */
export type ParamValues = Record<string, string | boolean>;

export type BuildStatus = "queued" | "running" | "done" | "error";

export type Build = {
  id: string;
  editor: string;
  params: Record<string, number | boolean | string>;
  status: BuildStatus;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  mesh: MeshInfo | null;
  file_url: string;
};

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** Все редакторы с сервера Next. API недоступен (сборка образа) → null, страница не падает. */
export async function loadEditors(): Promise<Editor[] | null> {
  try {
    const r = await fetch(`${apiInternalUrl()}/api/v1/editors`, { next: { revalidate: 600 } });
    if (!r.ok) return null;
    return ((await r.json()) as { editors: Editor[] }).editors;
  } catch {
    return null;
  }
}

/** Один редактор; нет такого — null. Ошибка сети тоже null: страница покажет «не найден». */
export async function loadEditor(slug: string): Promise<Editor | null> {
  if (!SLUG_RE.test(slug)) return null;
  try {
    const r = await fetch(`${apiInternalUrl()}/api/v1/editors/${slug}`, { next: { revalidate: 600 } });
    if (!r.ok) return null;
    return (await r.json()) as Editor;
  } catch {
    return null;
  }
}

/** Значения формы по умолчанию из схемы. */
export function defaultValues(editor: Editor): ParamValues {
  const values: ParamValues = {};
  for (const p of editor.params) {
    values[p.name] = p.type === "bool" ? Boolean(p.default) : String(p.default);
  }
  return values;
}

/** «12,5» → 12.5; пусто или мусор → NaN. */
export function parseNumber(text: string): number {
  const t = text.trim().replace(",", ".");
  if (t === "") return NaN;
  return Number(t);
}

/** Единица после числа: «мм» → « мм», пусто → «». */
function unitSuffix(p: EditorParam): string {
  return p.unit ? ` ${p.unit}` : "";
}

/** Проверка одного поля — те же тексты, что отдаёт сервер. null — всё хорошо. */
export function validateValue(p: EditorParam, value: string | boolean): string | null {
  if (p.type === "number") {
    const n = typeof value === "boolean" ? NaN : parseNumber(value);
    if (!Number.isFinite(n)) return "Нужно число.";
    if (p.integer && !Number.isInteger(n)) return "Нужно целое число.";
    if (p.min !== null && n < p.min) return `Не меньше ${fmt(p.min)}${unitSuffix(p)}.`;
    if (p.max !== null && n > p.max) return `Не больше ${fmt(p.max)}${unitSuffix(p)}.`;
    return null;
  }
  if (p.type === "bool") return typeof value === "boolean" ? null : "Нужно да или нет.";
  if (p.type === "choice") {
    return p.options.some((o) => o.value === value) ? null : "Выберите один из вариантов.";
  }
  const text = String(value).trim();
  if (text.length > p.maxlen) return `Не длиннее ${p.maxlen} символов.`;
  if (/[\u0000-\u001f]/.test(text)) return "Текст без переносов строк и служебных символов.";
  return null;
}

/** Правило «a < b» / «h >= 2»: имена — числовые параметры, справа может стоять число. */
const CHECK_RE = /^\s*([a-z_][a-z0-9_]*)\s*(<=|>=|<|>)\s*([a-z_][a-z0-9_]*|-?\d+(?:\.\d+)?)\s*$/;

function checkHolds(check: EditorCheck, values: ParamValues): boolean {
  const m = CHECK_RE.exec(check.rule);
  if (!m) return true; // непонятное правило проверит сервер
  const [, left, op, right] = m;
  const a = parseNumber(String(values[left] ?? ""));
  const b = /^-?\d/.test(right) ? Number(right) : parseNumber(String(values[right] ?? ""));
  if (!Number.isFinite(a) || !Number.isFinite(b)) return true;
  switch (op) {
    case "<":
      return a < b;
    case "<=":
      return a <= b;
    case ">":
      return a > b;
    default:
      return a >= b;
  }
}

/**
 * Ошибки по всем полям: сначала каждое поле по схеме, потом (если поля в порядке) правила
 * между параметрами — ошибка правила вешается на левый параметр. Пустой объект — можно строить.
 */
export function validateValues(editor: Editor, values: ParamValues): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const p of editor.params) {
    const error = validateValue(p, values[p.name] ?? defaultValues(editor)[p.name]);
    if (error) errors[p.name] = error;
  }
  if (Object.keys(errors).length === 0) {
    for (const check of editor.checks) {
      if (!checkHolds(check, values)) {
        const left = CHECK_RE.exec(check.rule)?.[1];
        if (left && !errors[left]) errors[left] = check.message;
      }
    }
  }
  return errors;
}

/** Значения формы → тело запроса POST /builds: числа числами, остальное как есть. */
export function toRequestParams(editor: Editor, values: ParamValues): Record<string, number | boolean | string> {
  const params: Record<string, number | boolean | string> = {};
  for (const p of editor.params) {
    const v = values[p.name];
    if (p.type === "number") params[p.name] = parseNumber(String(v));
    else if (p.type === "bool") params[p.name] = Boolean(v);
    else params[p.name] = String(v).trim();
  }
  return params;
}

/** Число для подписи: 12.5 → «12,5», 20 → «20». */
export function fmt(n: number): string {
  return String(Number(n.toFixed(3))).replace(".", ",");
}

export const BUILD_STATUS_TEXT: Record<BuildStatus, string> = {
  queued: "В очереди…",
  running: "Строим модель…",
  done: "Готово",
  error: "Не удалось построить",
};

/**
 * Через сколько миллисекунд после последнего изменения параметров модель пересобирается сама (B43).
 * Меньше — лишние сборки на каждую цифру, больше — кажется, что превью «не слушается».
 */
export const AUTO_BUILD_MS = 900;

/** Ползунок рядом с числом показываем, только если у параметра заданы обе границы. */
export function hasSlider(p: EditorParam): boolean {
  return p.type === "number" && p.min !== null && p.max !== null && p.max > p.min;
}

/** Шаг ползунка: из схемы; у целых — 1; иначе ~200 делений на диапазон, округлённые до 0,1 / 0,5 / 1. */
export function sliderStep(p: EditorParam): number {
  if (p.step) return p.step;
  if (p.integer) return 1;
  const span = (p.max ?? 0) - (p.min ?? 0);
  if (span <= 20) return 0.1;
  if (span <= 100) return 0.5;
  return 1;
}

/** Подпись под полем: «от 4 до 200 мм · подсказка». Без границ — только подсказка. */
export function rangeHint(p: EditorParam): string {
  const u = p.unit ? ` ${p.unit}` : "";
  let range = "";
  if (p.type === "number") {
    if (p.min !== null && p.max !== null) range = `от ${fmt(p.min)} до ${fmt(p.max)}${u}`;
    else if (p.min !== null) range = `не меньше ${fmt(p.min)}${u}`;
    else if (p.max !== null) range = `не больше ${fmt(p.max)}${u}`;
  }
  return [range, p.hint].filter(Boolean).join(" · ");
}

/** Одинаковые ли параметры (чтобы не пересобирать то, что уже построено). */
export function sameParams(a: Record<string, unknown> | null | undefined, b: Record<string, unknown>): boolean {
  if (!a) return false;
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) if (a[k] !== b[k]) return false;
  return true;
}
