"use client";

/**
 * Панель инструмента «Текст» интерактивного редактора (B60, docs/EDITOR.md).
 * Правит черновик (пока надпись не поставлена) или выбранное наложение: текст, шрифт, размер,
 * глубина, выпукло/врезано; переключает гизмо (двигать / повернуть / размер); «Применить»
 * отправляет наложение на сервер (POST /api/v1/uploads/{id}/embosses с placement), ждёт
 * сборку и ведёт на страницу новой модели. Живой 3D-текст в окне — B61.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Field, Select } from "@/components/ui";
import { type EmbossJob, FONTS, LIMITS, STATUS_TEXT, WARNING_TEXT } from "@/lib/emboss";
import { fmt } from "@/lib/emboss";
import { upAngle, rotateUp } from "@/lib/editor/math";
import { useIsPhone } from "@/lib/editor/phone";
import {
  activeDraft,
  type EditorStore,
  type Gizmo,
  type OverlayDraft,
  overlayProblem,
  selectedOverlay,
  toEmbossParams,
  useEditor,
} from "@/lib/editor/store";

const POLL_MS = 1500;

const GIZMOS: { value: Gizmo; label: string }[] = [
  { value: "translate", label: "Двигать" },
  { value: "rotate", label: "Повернуть" },
  { value: "scale", label: "Размер" },
];

type Props = { uploadId: string; store: EditorStore };

export default function TextToolPanel({ uploadId, store }: Props) {
  const router = useRouter();
  const selected = useEditor(store, selectedOverlay);
  /** На телефоне кнопки крупнее — под палец (B60b). */
  const btn = useIsPhone() ? "md" : "sm";
  const draft = useEditor(store, activeDraft);
  const gizmo = useEditor(store, (s) => s.gizmo);
  const count = useEditor(store, (s) => s.overlays.length);
  const [job, setJob] = useState<EmbossJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Пока сервер наносит надпись — опрашиваем; готово → на страницу результата.
  useEffect(() => {
    if (!job) return;
    if (job.status === "done" && job.result_upload_id) {
      router.push(`/upload/${job.result_upload_id}`);
      return;
    }
    if (job.status !== "queued" && job.status !== "running") return;
    const timer = setTimeout(async () => {
      const r = await fetch(`/api/v1/uploads/${uploadId}/embosses/${job.id}`);
      if (r.ok) setJob((await r.json()) as EmbossJob);
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [job, uploadId, router]);

  function set(patch: Partial<OverlayDraft>) {
    if (selected) store.dispatch({ type: "update", id: selected.id, patch });
    else store.dispatch({ type: "draft", patch });
    setJob(null);
    setError(null);
  }

  function rotateBy(deg: number) {
    if (!selected) return;
    store.dispatch({ type: "move", id: selected.id, placement: rotateUp(selected.placement, (deg * Math.PI) / 180) });
  }

  async function apply() {
    const problem = overlayProblem(selected);
    if (problem || !selected) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/v1/uploads/${uploadId}/embosses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params: toEmbossParams(selected) }),
      });
      const body = (await r.json().catch(() => ({}))) as { detail?: { errors?: Record<string, string> } | string };
      if (r.status === 422 && typeof body.detail === "object" && body.detail?.errors) {
        setError(Object.values(body.detail.errors).join(" "));
        return;
      }
      if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Ошибка ${r.status}.`);
      setJob(body as EmbossJob);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const working = busy || (job !== null && (job.status === "queued" || job.status === "running"));
  const angleDeg = selected ? Math.round((upAngle(selected.placement) * 180) / Math.PI) : 0;

  return (
    <div className="flex flex-col gap-3" data-testid="text-tool">
      <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
        {selected
          ? "Надпись выбрана: тяните стрелки гизмо, чтобы двигать по поверхности, или правьте параметры."
          : count === 0
            ? "Наведите на модель и нажмите — надпись встанет в эту точку и прилипнет к поверхности."
            : "Нажмите на надпись, чтобы изменить её, или на свободное место модели — поставить ещё одну."}
      </p>

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

      <Range id="ed-size" label="Размер букв" unit="мм" value={draft.size_mm} min={LIMITS.size.min} max={60} step={0.5} onChange={(v) => set({ size_mm: v })} />
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
            Убрать надпись
          </Button>
        </>
      )}

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

      <Button onClick={apply} disabled={working || !selected} data-testid="apply">
        {working ? "Наносим…" : "Применить"}
      </Button>
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
