"use client";

/**
 * Панель инструмента «Текст» интерактивного редактора (B60, docs/EDITOR.md).
 * Правит черновик (пока надпись не поставлена) или выбранное наложение: текст, шрифт, размер,
 * глубина, выпукло/врезано; переключает гизмо (двигать / повернуть / размер); «Применить»
 * отправляет наложение на сервер (POST /api/v1/uploads/{id}/embosses с placement), ждёт
 * сборку и ведёт на страницу новой модели. Окно показывает живой 3D-текст (B61): каждая
 * правка здесь сразу видна на модели; «Цвет в окне» — только для просмотра.
 * Та же панель — для инструмента «Логотип» (B62): вместо текста и шрифта — загрузка SVG,
 * размер — ширина логотипа; размещение, гизмо и «Применить» — общие с надписью.
 */

import LogoUpload from "@/components/editor/LogoUpload";
import OverlayList from "@/components/editor/OverlayList";
import { Button, Field, Select } from "@/components/ui";
import { FONTS, LIMITS, STATUS_TEXT, WARNING_TEXT } from "@/lib/emboss";
import { fmt } from "@/lib/emboss";
import type { ApplyState } from "@/lib/editor/apply";
import { upAngle, rotateUp } from "@/lib/editor/math";
import { panelHint, useIsPhone } from "@/lib/editor/phone";
import { PINCH_MAX_MM, PREVIEW_COLORS } from "@/lib/editor/text3d";
import {
  activeDraft,
  type EditorStore,
  type Gizmo,
  type OverlayDraft,
  selectedOverlay,
  useEditor,
} from "@/lib/editor/store";

const GIZMOS: { value: Gizmo; label: string }[] = [
  { value: "translate", label: "Двигать" },
  { value: "rotate", label: "Повернуть" },
  { value: "scale", label: "Размер" },
];

/** applyState — общий с «✓ Готово» хук useApply (lib/editor/apply.ts), создаётся на странице. */
type Props = { uploadId: string; store: EditorStore; applyState: ApplyState };

export default function TextToolPanel({ uploadId, store, applyState }: Props) {
  const { job, error, working, apply, reset } = applyState;
  const selected = useEditor(store, selectedOverlay);
  /** На телефоне кнопки крупнее — под палец (B60b). */
  const phone = useIsPhone();
  const btn = phone ? "md" : "sm";
  const draft = useEditor(store, activeDraft);
  const gizmo = useEditor(store, (s) => s.gizmo);
  const overlays = useEditor(store, (s) => s.overlays);
  const count = overlays.length;
  const previewColor = useEditor(store, (s) => s.previewColor);
  const isLogo = useEditor(store, (s) => s.tool === "logo");
  const hasLogo = useEditor(store, (s) => s.logo !== null);
  const what = isLogo ? "Логотип" : "Надпись";
  function set(patch: Partial<OverlayDraft>) {
    if (selected) store.dispatch({ type: "update", id: selected.id, patch });
    else store.dispatch({ type: "draft", patch });
    reset();
  }

  function rotateBy(deg: number) {
    if (!selected) return;
    store.dispatch({ type: "move", id: selected.id, placement: rotateUp(selected.placement, (deg * Math.PI) / 180) });
  }

  const angleDeg = selected ? Math.round((upAngle(selected.placement) * 180) / Math.PI) : 0;

  return (
    <div className="flex flex-col gap-3" data-testid={isLogo ? "logo-tool" : "text-tool"}>
      <OverlayList store={store} size={btn} />
      <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
        {panelHint({ kind: isLogo ? "logo" : "text", phone, selected: Boolean(selected), hasLogo, count })}
      </p>

      {isLogo ? (
        <LogoUpload uploadId={uploadId} store={store} />
      ) : (
        <>
          <Field
            id="ed-text"
            label="Текст"
            value={draft.text}
            maxLength={LIMITS.textMaxlen}
            placeholder="Например, «Маше на память»"
            onChange={(e) => set({ text: e.target.value })}
          />

          <div className="grid grid-cols-2 gap-3">
            <Select id="ed-font" label="Шрифт" options={FONTS} value={draft.font} onChange={(e) => set({ font: e.target.value as OverlayDraft["font"] })} />
            <label className="flex items-end gap-2 pb-2 text-sm">
              <input type="checkbox" checked={draft.bold} onChange={(e) => set({ bold: e.target.checked })} /> Жирный
            </label>
          </div>
        </>
      )}

      <Range id="ed-size" label={isLogo ? "Ширина логотипа" : "Размер букв"} unit="мм" value={draft.size_mm} min={LIMITS.size.min} max={PINCH_MAX_MM} step={0.5} onChange={(v) => set({ size_mm: v })} />
      <Range id="ed-depth" label={draft.mode === "engraved" ? "Глубина" : "Высота"} unit="мм" value={draft.depth_mm} min={LIMITS.depth.min} max={5} step={0.1} onChange={(v) => set({ depth_mm: v })} />

      <Segmented
        size={btn}
        label="Как наносим"
        value={draft.mode}
        options={[
          { value: "raised", label: "Выпукло" },
          { value: "engraved", label: "Врезано" },
        ]}
        onChange={(v) => set({ mode: v as OverlayDraft["mode"] })}
      />

      <div className="flex flex-col gap-1">
        <span className="text-sm font-semibold">Цвет в окне</span>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={`Цвет: ${what.toLowerCase()} в окне просмотра`}>
          {PREVIEW_COLORS.map((c) => (
            <button
              key={c.value}
              type="button"
              role="radio"
              aria-checked={c.value === previewColor}
              aria-label={c.label}
              title={c.label}
              onClick={() => store.dispatch({ type: "previewColor", color: c.value })}
              className="h-8 w-8 rounded-full"
              style={{
                background: c.value,
                border: "1px solid var(--line)",
                outline: c.value === previewColor ? "3px solid var(--filament)" : "none",
                outlineOffset: 2,
              }}
            />
          ))}
        </div>
        <span className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Только для просмотра. Цвет пластика выбирается при заказе или в «Цвете».
        </span>
      </div>

      {selected && (
        <>
          <Segmented size={btn} label="Гизмо" value={gizmo} options={GIZMOS} onChange={(v) => store.dispatch({ type: "gizmo", gizmo: v as Gizmo })} />
          <div className="flex items-center gap-2 text-sm">
            <span style={{ color: "var(--ink-muted)" }}>Поворот {angleDeg}°</span>
            <Button variant="ghost" size={btn} onClick={() => rotateBy(-15)} aria-label="Повернуть на 15° по часовой">
              ↻ 15°
            </Button>
            <Button variant="ghost" size={btn} onClick={() => rotateBy(15)} aria-label="Повернуть на 15° против часовой">
              ↺ 15°
            </Button>
          </div>
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
            Точка: {selected.placement.point.map((v) => fmt(v)).join(", ")} мм
          </p>
          <Button variant="ghost" size={btn} onClick={() => store.dispatch({ type: "remove", id: selected.id })}>
            {isLogo ? "Убрать логотип" : "Убрать надпись"}
          </Button>
        </>
      )}

      {/* Низ панели прилипает: на телефоне «Применить» всегда на виду над инструментами,
          а не в конце прокрутки (QA 2026-11-08). */}
      <div className="sticky -bottom-3 -mx-4 flex flex-col gap-2 border-t px-4 pb-3 pt-2" style={{ background: "var(--surface-raised)", borderColor: "var(--line)" }}>
      {error && (
        <p className="text-sm" role="alert" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      {job && job.status !== "done" && (
        <p className="text-sm" aria-live="polite">
          {STATUS_TEXT[job.status]}
          {job.error ? ` ${job.error}` : ""}
          {job.warnings?.map((w) => ` ${WARNING_TEXT[w] ?? w}`)}
        </p>
      )}

      <Button onClick={apply} disabled={working || count === 0} data-testid="apply">
        {working ? "Наносим…" : count > 1 ? `Применить все (${count})` : "Применить"}
      </Button>
      </div>
    </div>
  );
}

function Range({ id, label, unit, value, min, max, step, onChange }: { id: string; label: string; unit: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-sm">
        <label htmlFor={id} className="font-semibold">
          {label}
        </label>
        <span>
          {fmt(value)} {unit}
        </span>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ accentColor: "var(--filament)" }} />
    </div>
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  size = "sm",
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-sm font-semibold">{label}</span>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <Button key={o.value} size={size} variant={o.value === value ? "primary" : "secondary"} role="radio" aria-checked={o.value === value} onClick={() => onChange(o.value)}>
            {o.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
