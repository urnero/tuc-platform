"use client";

/**
 * Список наложений редактора и «Отменить / Повторить» (B65, docs/EDITOR.md).
 * Нажатие на строку выбирает наложение (как клик в окне), ↑/↓ меняют порядок — в этом
 * порядке сервер наносит их одной сборкой; × убирает. Всё — действия стора, отменяемые.
 */

import type { ReactNode } from "react";
import { Button } from "@/components/ui";
import { type EditorStore, overlayLabel, useEditor } from "@/lib/editor/store";

type Props = { store: EditorStore; size: "sm" | "md" };

export default function OverlayList({ store, size }: Props) {
  const overlays = useEditor(store, (s) => s.overlays);
  const selectedId = useEditor(store, (s) => s.selectedId);
  const canUndo = useEditor(store, (s) => s.past.length > 0);
  const canRedo = useEditor(store, (s) => s.future.length > 0);

  return (
    <div className="flex flex-col gap-2" data-testid="overlay-list">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">Наложения{overlays.length > 0 ? ` · ${overlays.length}` : ""}</span>
        <div className="flex gap-1">
          <Button variant="ghost" size={size} disabled={!canUndo} onClick={() => store.dispatch({ type: "undo" })} aria-label="Отменить (Ctrl+Z)" title="Отменить (Ctrl+Z)" data-testid="undo">
            ↶
          </Button>
          <Button variant="ghost" size={size} disabled={!canRedo} onClick={() => store.dispatch({ type: "redo" })} aria-label="Повторить (Ctrl+Shift+Z)" title="Повторить (Ctrl+Shift+Z)" data-testid="redo">
            ↷
          </Button>
        </div>
      </div>
      {overlays.length === 0 ? (
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Пока пусто. Поставьте надпись или логотип — можно несколько, они нанесутся одной сборкой.
        </p>
      ) : (
        <ol className="flex flex-col gap-1">
          {overlays.map((o, i) => {
            const active = o.id === selectedId;
            return (
              <li
                key={o.id}
                className="flex items-center gap-1 rounded-lg px-2 py-1 text-sm"
                style={{ border: `1px solid ${active ? "var(--filament)" : "var(--line)"}`, background: active ? "var(--surface)" : undefined }}
              >
                <button
                  type="button"
                  className="min-h-[36px] flex-1 truncate text-left"
                  aria-pressed={active}
                  onClick={() => store.dispatch({ type: "select", id: active ? null : o.id })}
                  data-testid="overlay-item"
                >
                  {i + 1}. {overlayLabel(o)}
                  <span className="ml-1 text-xs" style={{ color: "var(--ink-muted)" }}>
                    {o.mode === "engraved" ? "врезано" : "выпукло"}
                  </span>
                </button>
                <IconBtn label={`Выше: ${overlayLabel(o)}`} disabled={i === 0} onClick={() => store.dispatch({ type: "reorder", id: o.id, dir: -1 })}>
                  ↑
                </IconBtn>
                <IconBtn label={`Ниже: ${overlayLabel(o)}`} disabled={i === overlays.length - 1} onClick={() => store.dispatch({ type: "reorder", id: o.id, dir: 1 })}>
                  ↓
                </IconBtn>
                <IconBtn label={`Убрать: ${overlayLabel(o)}`} onClick={() => store.dispatch({ type: "remove", id: o.id })}>
                  ×
                </IconBtn>
              </li>
            );
          })}
        </ol>
      )}
      {overlays.length > 1 && (
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Наносятся сверху вниз: врезанное ниже выпуклого прорежет и его.
        </p>
      )}
    </div>
  );
}

function IconBtn({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      className="h-9 w-9 shrink-0 rounded-md text-base disabled:opacity-30"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
