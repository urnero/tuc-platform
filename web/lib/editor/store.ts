/**
 * Состояние интерактивного редактора (B60, docs/EDITOR.md): какой инструмент выбран, список
 * наложений (надпись / логотип с размещением на поверхности), какое выбрано, что под курсором.
 *
 * Чистый редьюсер `reduce(state, action)` — его проверяют тесты; `createEditorStore()` —
 * маленькое хранилище для React (useSyncExternalStore), без сторонних библиотек.
 * Панели и 3D-окно читают одно и то же состояние и шлют действия, друг о друге не знают.
 */

import { useSyncExternalStore } from "react";
import { LIMITS, type EmbossFont, type EmbossParams, type EmbossStyle } from "../emboss";
import { LOGO_DEFAULT_MM } from "./logo3d";
import { type Placement, roundPlacement } from "./math";

export type Tool = "text" | "logo" | "color" | "done";
export type Gizmo = "translate" | "rotate" | "scale";

/** Параметры наложения без размещения — то, что правят в панели. */
export type OverlayDraft = {
  kind: "text" | "logo";
  text: string;
  font: EmbossFont;
  bold: boolean;
  size_mm: number;
  depth_mm: number;
  mode: EmbossStyle;
};

export type Overlay = OverlayDraft & { id: string; placement: Placement };

/** Логотип модели (B62): один на загрузку, лежит на сервере (POST/GET …/uploads/{id}/logo). */
export type LogoInfo = { name: string; svg: string };

export type EditorState = {
  tool: Tool;
  overlays: Overlay[];
  selectedId: string | null;
  /** Предпросмотр под курсором: куда встанет наложение, если кликнуть. null — курсор не на модели. */
  hover: Placement | null;
  gizmo: Gizmo;
  /** Параметры для следующего наложения; при выборе наложения панель правит его, а не черновик. */
  draft: OverlayDraft;
  /** Цвет надписей в окне (B61) — только для просмотра, на сервер не уходит. */
  previewColor: string;
  /** Загруженный SVG-логотип — его контуры видны в окне; null — ещё не загружен. */
  logo: LogoInfo | null;
  /** История (B65): прошлые списки наложений для «Отменить» и отменённые — для «Повторить». */
  past: Overlay[][];
  future: Overlay[][];
  /**
   * Ключ последней правки: подряд идущие правки одного поля одного наложения (набор текста,
   * ползунок, щипок) — один шаг истории, а не сто.
   */
  lastEdit: string | null;
};

export type Action =
  | { type: "tool"; tool: Tool }
  | { type: "hover"; placement: Placement | null }
  | { type: "place"; placement: Placement }
  | { type: "select"; id: string | null }
  | { type: "update"; id: string; patch: Partial<OverlayDraft> }
  | { type: "move"; id: string; placement: Placement }
  | { type: "remove"; id: string }
  | { type: "gizmo"; gizmo: Gizmo }
  | { type: "draft"; patch: Partial<OverlayDraft> }
  | { type: "restore"; overlay: Overlay }
  | { type: "previewColor"; color: string }
  | { type: "logo"; logo: LogoInfo | null }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reorder"; id: string; dir: -1 | 1 };

/** Сколько шагов назад помнит «Отменить». */
export const HISTORY_MAX = 50;

export const DEFAULT_DRAFT: OverlayDraft = {
  kind: "text",
  text: "",
  font: "sans",
  bold: true,
  size_mm: 10,
  depth_mm: 1,
  mode: "raised",
};

export const INITIAL_STATE: EditorState = {
  tool: "text",
  overlays: [],
  selectedId: null,
  hover: null,
  gizmo: "translate",
  draft: DEFAULT_DRAFT,
  previewColor: "#f26a1b",
  logo: null,
  past: [],
  future: [],
  lastEdit: null,
};

let counter = 0;
/** Короткий id наложения — только внутри страницы, на сервер не уходит. */
export function nextId(): string {
  counter += 1;
  return `o${counter}`;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Границы размера и глубины — те же, что у формы тиснения и на сервере. */
export function clampDraft(patch: Partial<OverlayDraft>): Partial<OverlayDraft> {
  const out = { ...patch };
  if (out.size_mm !== undefined) out.size_mm = clamp(out.size_mm, LIMITS.size.min, LIMITS.size.max);
  if (out.depth_mm !== undefined) out.depth_mm = clamp(out.depth_mm, LIMITS.depth.min, LIMITS.depth.max);
  if (out.text !== undefined) out.text = out.text.slice(0, LIMITS.textMaxlen);
  return out;
}

/**
 * Черновик под инструмент: «Текст» и «Логотип» — свой вид; при смене вида размер
 * возвращается к привычному (буквы 10 мм, логотип 20 мм в ширину).
 */
function draftFor(draft: OverlayDraft, tool: Tool): OverlayDraft {
  if (tool !== "text" && tool !== "logo") return draft;
  if (draft.kind === tool) return draft;
  return { ...draft, kind: tool, size_mm: tool === "logo" ? LOGO_DEFAULT_MM : DEFAULT_DRAFT.size_mm };
}

/**
 * Новый список наложений с записью в историю (B65). key — для склейки подряд идущих правок
 * одного поля (null — всегда отдельный шаг). Выбор, если выбранного больше нет, снимается.
 */
function commit(state: EditorState, overlays: Overlay[], key: string | null, extra: Partial<EditorState> = {}): EditorState {
  const same = key !== null && key === state.lastEdit;
  const past = same ? state.past : [...state.past, state.overlays].slice(-HISTORY_MAX);
  return { ...state, ...extra, overlays, past, future: [], lastEdit: key };
}

/** Шаг по истории: список наложений из стопки `from`, текущий — в стопку `to`. */
function travel(state: EditorState, dir: "undo" | "redo"): EditorState {
  const from = dir === "undo" ? state.past : state.future;
  if (from.length === 0) return state;
  const overlays = from[from.length - 1];
  const rest = from.slice(0, -1);
  const to = [...(dir === "undo" ? state.future : state.past), state.overlays];
  const selectedId = overlays.some((o) => o.id === state.selectedId) ? state.selectedId : null;
  return {
    ...state,
    overlays,
    selectedId,
    hover: null,
    lastEdit: null,
    past: dir === "undo" ? rest : to,
    future: dir === "undo" ? to : rest,
  };
}

export function reduce(state: EditorState, action: Action): EditorState {
  switch (action.type) {
    case "tool":
      // Смена инструмента снимает выбор и предпросмотр; черновик подстраивается под инструмент.
      return {
        ...state,
        tool: action.tool,
        selectedId: null,
        hover: null,
        draft: draftFor(state.draft, action.tool),
      };
    case "hover":
      // Пока наложение выбрано, плашка под курсором не нужна — им управляет гизмо.
      return state.selectedId ? state : { ...state, hover: action.placement };
    case "place": {
      if (state.tool !== "text" && state.tool !== "logo") return state;
      const overlay: Overlay = { ...state.draft, kind: state.tool, id: nextId(), placement: action.placement };
      return commit(state, [...state.overlays, overlay], null, { selectedId: overlay.id, hover: null });
    }
    case "select": {
      // Выбрали логотип, стоя на «Тексте» (из списка или кликом в окне), — панель
      // переключается на его инструмент, иначе править было бы нечем.
      const o = state.overlays.find((x) => x.id === action.id);
      const tool = o && (state.tool === "text" || state.tool === "logo") ? o.kind : state.tool;
      return { ...state, tool, selectedId: action.id, hover: null, lastEdit: null, draft: draftFor(state.draft, tool) };
    }
    case "update": {
      if (!state.overlays.some((o) => o.id === action.id)) return state;
      const patch = clampDraft(action.patch);
      const key = `update:${action.id}:${Object.keys(patch).sort().join(",")}`;
      return commit(state, state.overlays.map((o) => (o.id === action.id ? { ...o, ...patch } : o)), key);
    }
    case "move":
      if (!state.overlays.some((o) => o.id === action.id)) return state;
      // Перемещение приходит один раз в конце перетаскивания — каждое отдельный шаг.
      return commit(state, state.overlays.map((o) => (o.id === action.id ? { ...o, placement: action.placement } : o)), null);
    case "remove":
      if (!state.overlays.some((o) => o.id === action.id)) return state;
      return commit(state, state.overlays.filter((o) => o.id !== action.id), null, {
        selectedId: state.selectedId === action.id ? null : state.selectedId,
      });
    case "reorder": {
      // Порядок = порядок нанесения на сервере: врезанное после выпуклого прорежет и его.
      const i = state.overlays.findIndex((o) => o.id === action.id);
      const j = i + action.dir;
      if (i < 0 || j < 0 || j >= state.overlays.length) return state;
      const next = [...state.overlays];
      [next[i], next[j]] = [next[j], next[i]];
      return commit(state, next, null);
    }
    case "undo":
      return travel(state, "undo");
    case "redo":
      return travel(state, "redo");
    case "gizmo":
      return { ...state, gizmo: action.gizmo };
    case "logo":
      return { ...state, logo: action.logo };
    case "previewColor":
      return /^#[0-9a-f]{6}$/i.test(action.color) ? { ...state, previewColor: action.color } : state;
    case "draft":
      return { ...state, draft: { ...state.draft, ...clampDraft(action.patch) } };
    case "restore":
      // Вернулись со страницы результата (B60c): прошлая надпись снова на модели и выбрана —
      // её можно двигать и править. Если она уже есть (повторный запрос) — не дублируем.
      if (state.overlays.some((o) => o.id === action.overlay.id)) return state;
      // В историю не пишем: это стартовое состояние страницы, «Отменить» его не убирает.
      return {
        ...state,
        tool: action.overlay.kind,
        overlays: [...state.overlays, action.overlay],
        selectedId: action.overlay.id,
        hover: null,
        draft: draftFor(state.draft, action.overlay.kind),
      };
    default:
      return state;
  }
}

export function selectedOverlay(state: EditorState): Overlay | null {
  return state.overlays.find((o) => o.id === state.selectedId) ?? null;
}

/** Что правит панель: выбранное наложение или черновик для следующего. */
export function activeDraft(state: EditorState): OverlayDraft {
  return selectedOverlay(state) ?? state.draft;
}

/**
 * Наложение → тело запроса `params` для POST /api/v1/uploads/{id}/embosses.
 * Размещение уходит в `placement`; face/dx/dy остаются по умолчанию — сервер их не использует.
 */
export function toEmbossParams(o: Overlay): EmbossParams & { placement: Placement & { size_mm: number; depth_mm: number; mode: EmbossStyle } } {
  const p = roundPlacement(o.placement);
  return {
    kind: o.kind,
    text: o.kind === "text" ? o.text.trim() : "",
    font: o.font,
    bold: o.bold,
    size_mm: o.size_mm,
    depth_mm: o.depth_mm,
    style: o.mode,
    face: "front",
    dx: 0,
    dy: 0,
    angle: 0,
    placement: { ...p, size_mm: o.size_mm, depth_mm: o.depth_mm, mode: o.mode },
  };
}

/**
 * Все наложения → тело запроса POST …/embosses (B65): первое в `params`, остальные в `more`.
 * Сервер наносит их одной сборкой по порядку списка.
 */
export function toEmbossBody(overlays: Overlay[]): { params: ReturnType<typeof toEmbossParams>; more: ReturnType<typeof toEmbossParams>[] } | null {
  if (overlays.length === 0) return null;
  const [first, ...rest] = overlays;
  return { params: toEmbossParams(first), more: rest.map(toEmbossParams) };
}

/** Подпись наложения в списке: «Надпись «Маше»» / «Логотип». */
export function overlayLabel(o: OverlayDraft): string {
  if (o.kind === "logo") return "Логотип";
  const t = o.text.trim();
  return t ? `Надпись «${t.length > 18 ? `${t.slice(0, 17)}…` : t}»` : "Надпись (пустая)";
}

/** Почему все наложения нельзя отправить (null — можно); у второго и дальше — с номером. */
export function overlaysProblem(overlays: Overlay[], hasLogo = false): string | null {
  if (overlays.length === 0) return overlayProblem(null);
  if (overlays.length > MAX_OVERLAYS) return `Не больше ${MAX_OVERLAYS} наложений за одну сборку — уберите лишние.`;
  for (let i = 0; i < overlays.length; i++) {
    const problem = overlayProblem(overlays[i], hasLogo);
    if (problem) return overlays.length > 1 ? `${i + 1}. ${overlayLabel(overlays[i])}: ${problem}` : problem;
  }
  return null;
}

/** Не больше наложений за одну сборку — как MAX_OVERLAYS в api/app/emboss.py. */
export const MAX_OVERLAYS = 10;

/** Почему наложение нельзя отправить на сервер (null — можно). hasLogo — SVG уже загружен. */
export function overlayProblem(o: Overlay | null, hasLogo = false): string | null {
  if (!o) return "Поставьте наложение на модель: наведите на поверхность и нажмите.";
  if (o.kind === "text" && !o.text.trim()) return "Введите текст надписи.";
  if (o.kind === "logo" && !hasLogo) return "Сначала загрузите логотип (SVG).";
  return null;
}

const isVec3 = (v: unknown): v is [number, number, number] =>
  Array.isArray(v) && v.length === 3 && v.every((x) => typeof x === "number" && Number.isFinite(x));

/**
 * Обратно к `toEmbossParams` (B60c): параметры прошлой сборки (GET …/embosses/{job_id}) →
 * наложение для стора. null — сборка старой формой (без `placement`): такую в редакторе
 * не поставить, клиент правит её на странице модели. Логотип (B62) тоже возвращается —
 * его SVG редактор берёт с сервера (GET …/uploads/{id}/logo).
 * id наложения — `job-<job_id>`, чтобы повторная загрузка не добавила вторую копию.
 */
export function overlayFromParams(jobId: string, params: Record<string, unknown> | null | undefined): Overlay | null {
  if (!params || (params.kind !== "text" && params.kind !== "logo")) return null;
  const kind = params.kind;
  const pl = params.placement as Record<string, unknown> | undefined;
  if (!pl || !isVec3(pl.point) || !isVec3(pl.normal) || !isVec3(pl.up)) return null;
  const num = (v: unknown, fallback: number) => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
  const mode = pl.mode === "engraved" || params.style === "engraved" ? "engraved" : "raised";
  const font = params.font === "serif" || params.font === "mono" ? params.font : "sans";
  const draft = clampDraft({
    text: kind === "text" && typeof params.text === "string" ? params.text : "",
    size_mm: num(pl.size_mm, num(params.size_mm, kind === "logo" ? LOGO_DEFAULT_MM : DEFAULT_DRAFT.size_mm)),
    depth_mm: num(pl.depth_mm, num(params.depth_mm, DEFAULT_DRAFT.depth_mm)),
  });
  return {
    ...DEFAULT_DRAFT,
    ...draft,
    kind,
    font,
    bold: params.bold !== false,
    mode,
    id: `job-${jobId}`,
    placement: { point: pl.point, normal: pl.normal, up: pl.up },
  };
}

/**
 * Все наложения прошлой сборки (B65): первое из params, остальные из params.more.
 * id остальных — `job-<job_id>-<номер>`. Пустой список — сборка старой формой.
 */
export function overlaysFromParams(jobId: string, params: Record<string, unknown> | null | undefined): Overlay[] {
  const first = overlayFromParams(jobId, params);
  if (!first || !params) return [];
  const more = Array.isArray(params.more) ? params.more : [];
  const rest = more
    .map((p, i) => overlayFromParams(`${jobId}-${i + 1}`, p as Record<string, unknown>))
    .filter((o): o is Overlay => o !== null);
  return [first, ...rest];
}

/**
 * ?tool=<инструмент> в ссылке на редактор (B62a): со страницы модели «Логотип в редакторе»
 * открывает сразу инструмент «Логотип». Неизвестное значение — null (инструмент по умолчанию).
 */
export function toolFromParam(value: string | null | undefined): Tool | null {
  return value === "text" || value === "logo" || value === "color" ? value : null;
}

/**
 * Ссылка «Изменить в редакторе» со страницы результата (B60c): редактор исходной модели
 * с прошлой надписью или логотипом. null — тиснение сделано старой формой.
 */
export function editAgainHref(emboss: { parent_id: string; job_id: string; params: Record<string, unknown> } | null | undefined): string | null {
  if (!emboss || !overlayFromParams(emboss.job_id, emboss.params)) return null;
  return `/upload/${encodeURIComponent(emboss.parent_id)}/edit?overlay=${encodeURIComponent(emboss.job_id)}`;
}

// --- хранилище для React -------------------------------------------------------------------

export type EditorStore = {
  getState: () => EditorState;
  dispatch: (action: Action) => void;
  subscribe: (fn: () => void) => () => void;
};

export function createEditorStore(initial: EditorState = INITIAL_STATE): EditorStore {
  let state = initial;
  const listeners = new Set<() => void>();
  return {
    getState: () => state,
    dispatch(action) {
      const next = reduce(state, action);
      if (next === state) return;
      state = next;
      listeners.forEach((fn) => fn());
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

/** Хук: часть состояния редактора; перерисовка только когда выбранная часть изменилась. */
export function useEditor<T>(store: EditorStore, pick: (s: EditorState) => T): T {
  return useSyncExternalStore(
    store.subscribe,
    () => pick(store.getState()),
    () => pick(store.getState()),
  );
}
