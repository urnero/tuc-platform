/**
 * Тиснение надписи / логотипа на загруженной модели (B30): типы ответа API,
 * подписи вариантов, проверка формы до отправки, сборка тела запроса.
 *
 * Сервер: POST /api/v1/uploads/{id}/embosses → запись сборки (status queued|running|done|error),
 * опрос GET …/embosses/{job_id}; после done — result_upload_id = новая загрузка с тиснением.
 */

export type EmbossKind = "text" | "logo" | "pattern";
/** Узор текстуры (B68): полосы · сетка · точки · соты — как PATTERNS в api/app/emboss.py. */
export type EmbossPattern = "lines" | "grid" | "dots" | "hex";
export type EmbossStyle = "raised" | "engraved";
export type EmbossFace = "top" | "bottom" | "front" | "back" | "left" | "right";
export type EmbossFont = "sans" | "serif" | "mono";
export type EmbossStatus = "queued" | "running" | "done" | "error";

/** Параметры, какими их принимает API (числа — числа). */
export type EmbossParams = {
  kind: EmbossKind;
  text: string;
  font: EmbossFont;
  bold: boolean;
  size_mm: number;
  depth_mm: number;
  style: EmbossStyle;
  face: EmbossFace;
  dx: number;
  dy: number;
  angle: number;
  /** Только для kind = "pattern" (B68): узор и шаг узора, мм. */
  pattern?: EmbossPattern;
  pitch_mm?: number;
};

/** То же, но как в полях формы: числа — строками, как их набрал клиент. */
export type EmbossForm = Omit<EmbossParams, "size_mm" | "depth_mm" | "dx" | "dy" | "angle" | "pattern" | "pitch_mm"> & {
  size_mm: string;
  depth_mm: string;
  dx: string;
  dy: string;
  angle: string;
};

export type EmbossJob = {
  id: string;
  upload_id: string;
  params: EmbossParams;
  status: EmbossStatus;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  /** «merged_without_boolean» — модель не замкнута, надпись просто приложена к ней. */
  warnings: string[];
  result_upload_id: string | null;
};

export const FACES: { value: EmbossFace; label: string }[] = [
  { value: "front", label: "Спереди" },
  { value: "top", label: "Сверху" },
  { value: "back", label: "Сзади" },
  { value: "left", label: "Слева" },
  { value: "right", label: "Справа" },
  { value: "bottom", label: "Снизу" },
];

export const FONTS: { value: EmbossFont; label: string }[] = [
  { value: "sans", label: "Без засечек" },
  { value: "serif", label: "С засечками" },
  { value: "mono", label: "Моноширинный" },
];

export const STYLES: { value: EmbossStyle; label: string }[] = [
  { value: "raised", label: "Выпуклое" },
  { value: "engraved", label: "Углублённое (вырез)" },
];

/** Узоры текстуры с подписями (B68) — те же, что PATTERN_LABELS на сервере. */
export const PATTERNS: { value: EmbossPattern; label: string }[] = [
  { value: "lines", label: "полосы" },
  { value: "grid", label: "сетка" },
  { value: "dots", label: "точки" },
  { value: "hex", label: "соты" },
];

/** Те же границы, что в api/app/emboss.py. */
export const LIMITS = {
  textMaxlen: 40,
  size: { min: 3, max: 200 },
  depth: { min: 0.2, max: 10 },
  /** Шаг узора текстуры (PITCH_MIN/PITCH_MAX) и не больше 50 повторов по стороне участка. */
  pitch: { min: 1, max: 50, maxRepeats: 50 },
  shift: 500,
  angle: 180,
  logoMaxBytes: 1024 * 1024,
};

export const DEFAULT_FORM: EmbossForm = {
  kind: "text",
  text: "",
  font: "sans",
  bold: true,
  size_mm: "10",
  depth_mm: "1",
  style: "raised",
  face: "front",
  dx: "0",
  dy: "0",
  angle: "0",
};

/**
 * Ссылка на интерактивный редактор модели. tool — сразу открыть инструмент
 * (B62a: «Логотип в редакторе» на странице модели вместо старой формы).
 */
export function editorHref(uploadId: string, tool?: "text" | "logo" | "pattern" | "color"): string {
  return `/upload/${uploadId}/edit${tool ? `?tool=${tool}` : ""}`;
}

/**
 * Чипы под окном 3D на странице модели (QA 08.11: вход в редактор был спрятан в свёрнутом
 * «Дополнительно» ниже калькулятора). Каждый ведёт сразу в нужный инструмент редактора.
 */
export const EDITOR_CHIPS: { tool: "text" | "logo" | "color"; label: string }[] = [
  { tool: "text", label: "Надпись" },
  { tool: "logo", label: "Логотип" },
  { tool: "color", label: "Цвет" },
];

export const STATUS_TEXT: Record<EmbossStatus, string> = {
  queued: "В очереди…",
  running: "Наносим…",
  done: "Готово",
  error: "Не получилось",
};

export const WARNING_TEXT: Record<string, string> = {
  merged_without_boolean:
    "Сетка модели не замкнута, поэтому надпись просто приложена к ней — слайсер соединит их при печати.",
  normal_flipped: "Поверхность модели в этой точке «вывернута»; надпись развернули наружу.",
  curved_surface: "Поверхность изогнута — края надписи могут быть тоньше.",
  edge_overhang:
    "Часть надписи выходит за край модели — эти буквы не напечатаются. Сдвиньте её к центру или уменьшите.",
};

/** Предупреждения сервера словами для страницы результата (B66): неизвестный код — как есть,
 *  `merged_without_boolean` клиенту не показываем (о нём и так сказано в проверке сетки). */
export function embossWarningTexts(warnings: string[] | undefined): string[] {
  return (warnings ?? []).filter((w) => w !== "merged_without_boolean").map((w) => WARNING_TEXT[w] ?? w);
}

/** «12,5» → 12.5; пусто → NaN. */
export function parseNumber(text: string): number {
  const t = text.trim().replace(",", ".");
  if (t === "") return NaN;
  return Number(t);
}

function checkNumber(text: string, min: number, max: number, unit = "мм"): string | null {
  const n = parseNumber(text);
  if (!Number.isFinite(n)) return "Нужно число.";
  if (n < min) return `Не меньше ${fmt(min)} ${unit}.`;
  if (n > max) return `Не больше ${fmt(max)} ${unit}.`;
  return null;
}

/** Проверка формы до отправки: ошибки по именам полей (пусто — всё хорошо). */
export function validateForm(form: EmbossForm, hasLogo: boolean): Partial<Record<keyof EmbossForm, string>> {
  const errors: Partial<Record<keyof EmbossForm, string>> = {};
  if (form.kind === "text") {
    const text = form.text.trim();
    if (!text) errors.text = "Введите надпись.";
    else if (text.length > LIMITS.textMaxlen) errors.text = `Не длиннее ${LIMITS.textMaxlen} символов.`;
  } else if (form.kind === "logo" && !hasLogo) {
    errors.kind = "Сначала загрузите логотип (SVG).";
  }
  const size = checkNumber(form.size_mm, LIMITS.size.min, LIMITS.size.max);
  if (size) errors.size_mm = size;
  const depth = checkNumber(form.depth_mm, LIMITS.depth.min, LIMITS.depth.max);
  if (depth) errors.depth_mm = depth;
  const dx = checkNumber(form.dx, -LIMITS.shift, LIMITS.shift);
  if (dx) errors.dx = dx;
  const dy = checkNumber(form.dy, -LIMITS.shift, LIMITS.shift);
  if (dy) errors.dy = dy;
  const angle = checkNumber(form.angle, -LIMITS.angle, LIMITS.angle, "°");
  if (angle) errors.angle = angle;
  return errors;
}

/** Поля формы → параметры для API. Зовётся после validateForm. */
export function toParams(form: EmbossForm): EmbossParams {
  return {
    kind: form.kind,
    text: form.kind === "text" ? form.text.trim() : "",
    font: form.font,
    bold: form.bold,
    size_mm: parseNumber(form.size_mm),
    depth_mm: parseNumber(form.depth_mm),
    style: form.style,
    face: form.face,
    dx: parseNumber(form.dx),
    dy: parseNumber(form.dy),
    angle: parseNumber(form.angle),
  };
}

/**
 * Варианты для панелей из GET /api/v1/emboss/options. Пока отвечает только то, что нужно
 * текстуре (B68): узоры и границы шага. Чего нет в ответе — берём из PATTERNS / LIMITS.
 */
export type EmbossOptions = {
  patterns: { value: EmbossPattern; label: string }[];
  pitch_mm: { min: number; max: number; max_repeats: number };
};

export const DEFAULT_OPTIONS: EmbossOptions = {
  patterns: PATTERNS,
  pitch_mm: { min: LIMITS.pitch.min, max: LIMITS.pitch.max, max_repeats: LIMITS.pitch.maxRepeats },
};

const isPattern = (v: unknown): v is EmbossPattern => PATTERNS.some((p) => p.value === v);

/** Ответ /emboss/options → EmbossOptions; незнакомые узоры и кривые числа отбрасываем. */
export function parseEmbossOptions(raw: unknown): EmbossOptions {
  const r = (raw ?? {}) as Record<string, unknown>;
  const patterns = Array.isArray(r.patterns)
    ? r.patterns
        .map((p) => p as Record<string, unknown>)
        .filter((p) => isPattern(p.value))
        .map((p) => ({ value: p.value as EmbossPattern, label: typeof p.label === "string" && p.label ? p.label : String(p.value) }))
    : [];
  const pitch = (r.pitch_mm ?? {}) as Record<string, unknown>;
  const num = (v: unknown, fallback: number) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : fallback);
  const d = DEFAULT_OPTIONS.pitch_mm;
  return {
    patterns: patterns.length ? patterns : DEFAULT_OPTIONS.patterns,
    pitch_mm: { min: num(pitch.min, d.min), max: num(pitch.max, d.max), max_repeats: num(pitch.max_repeats, d.max_repeats) },
  };
}

/** Подпись узора: «соты»; неизвестный — как есть. */
export function patternLabel(pattern: string): string {
  return PATTERNS.find((p) => p.value === pattern)?.label ?? pattern;
}

/** Проверка SVG-файла до отправки. Возвращает текст ошибки или null. */
export function validateLogoFile(name: string, sizeBytes: number): string | null {
  if (!/\.svg$/i.test(name)) return "Логотип — только SVG (векторная картинка).";
  if (sizeBytes <= 0) return "Файл пустой.";
  if (sizeBytes > LIMITS.logoMaxBytes) return "Логотип больше 1 МБ.";
  return null;
}

/** 12.5 → «12,5», 20 → «20». */
export function fmt(n: number): string {
  return String(Number(n.toFixed(2))).replace(".", ",");
}
