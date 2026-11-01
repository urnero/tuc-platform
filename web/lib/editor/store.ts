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

export type EditorState = {
  tool: Tool;
  overlays: Overlay[];
  selectedId: string | null;
  /** Предпросмотр под курсором: куда встанет наложение, если кликнуть. null — курсор не на модели. */
  hover: Placement | null;
  gizmo: Gizmo;
  /** Параметры для следующего наложения; при выборе наложения панель правит его, а не черновик. */
  draft: OverlayDraft;
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
  | { type: "draft"; patch: Partial<OverlayDraft> };

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

export function reduce(state: EditorState, action: Action): EditorState {
  switch (action.type) {
    case "tool":
      // Смена инструмента снимает выбор и предпросмотр; черновик подстраивается под инструмент.
      return {
        ...state,
        tool: action.tool,
        selectedId: null,
        hover: null,
        draft:
          action.tool === "text" || action.tool === "logo"
            ? { ...state.draft, kind: action.tool }
            : state.draft,
      };
    case "hover":
      // Пока наложение выбрано, плашка под курсором не нужна — им управляет гизмо.
      return state.selectedId ? state : { ...state, hover: action.placement };
    case "place": {
      if (state.tool !== "text" && state.tool !== "logo") return state;
      const overlay: Overlay = { ...state.draft, kind: state.tool, id: nextId(), placement: action.placement };
      return { ...state, overlays: [...state.overlays, overlay], selectedId: overlay.id, hover: null };
    }
    case "select":
      return { ...state, selectedId: action.id, hover: null };
    case "update":
      return {
        ...state,
        overlays: state.overlays.map((o) => (o.id === action.id ? { ...o, ...clampDraft(action.patch) } : o)),
      };
    case "move":
      return {
        ...state,
        overlays: state.overlays.map((o) => (o.id === action.id ? { ...o, placement: action.placement } : o)),
      };
    case "remove":
      return {
        ...state,
        overlays: state.overlays.filter((o) => o.id !== action.id),
        selectedId: state.selectedId === action.id ? null : state.selectedId,
      };
    case "gizmo":
      return { ...state, gizmo: action.gizmo };
    case "draft":
      return { ...state, draft: { ...state.draft, ...clampDraft(action.patch) } };
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

/** Почему наложение нельзя отправить на сервер (null — можно). */
export function overlayProblem(o: Overlay | null): string | null {
  if (!o) return "Поставьте надпись на модель: наведите на поверхность и нажмите.";
  if (o.kind === "text" && !o.text.trim()) return "Введите текст надписи.";
  if (o.kind === "logo") return "Загрузка логотипа появится в следующей версии редактора.";
  return null;
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
