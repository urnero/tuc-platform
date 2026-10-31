"use client";

/**
 * Блок «Раскраска по частям» на странице загрузки (B31).
 *
 * 1. «Разобрать на детали» → GET /api/v1/uploads/{id}/parts (детали = отдельные куски сетки)
 *    и GET /api/v1/paint/colors (палитра из config/colors.yaml).
 * 2. Список деталей, у каждой — выбор цвета; 3D-просмотр грузит …/parts/file и красит
 *    треугольники по диапазонам деталей прямо в браузере — цвета меняются сразу.
 * 3. «Собрать модель в цветах» → POST /api/v1/uploads/{id}/paints → пока queued/running,
 *    опрашиваем GET раз в 2 секунды → done: ссылка на новую загрузку /upload/<result_upload_id>
 *    (3MF, каждая деталь своим цветом — там расчёт, цена и заказ). Исходная модель не меняется.
 *
 * Инструмент «Цвет» (B63): деталь под курсором подсвечивается, клик/тап по ней выбирает её и
 * открывает палитру рядом с точкой клика; «Всё одним цветом»; «Отменить / Повторить»
 * (Ctrl+Z, Ctrl+Shift+Z или Ctrl+Y); больше 4 цветов — предупреждение о печати в несколько заходов.
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type ColorHistory,
  colorsWarning,
  defaultColors,
  historyKey,
  historyPush,
  historyRedo,
  historyStart,
  historyUndo,
  lighten,
  partAtFace,
  type PaintColor,
  type PaintJob,
  type Part,
  partCaption,
  partRanges,
  type PartsResponse,
  STATUS_TEXT,
  summaryLine,
  validateColors,
} from "@/lib/paint";

const ModelViewer = dynamic(() => import("@/components/ModelViewer"), { ssr: false });

const POLL_MS = 2000;
const BORDER = { borderColor: "var(--ink-muted)" };
const FIELD = { borderColor: "var(--ink-muted)", background: "var(--surface)", color: "var(--ink)" };

type Props = { uploadId: string };

export default function PaintPanel({ uploadId }: Props) {
  const [parts, setParts] = useState<Part[] | null>(null);
  // Единицы, для которых сделана разборка: в адресе STL, чтобы 3D-просмотр (кэш по адресу)
  // не показал старую геометрию после смены «мм → дюймы».
  const [partsUnits, setPartsUnits] = useState<string>("mm");
  const [palette, setPalette] = useState<PaintColor[]>([]);
  const [hist, setHist] = useState<ColorHistory>(() => historyStart([]));
  const colors = hist.present;
  // Деталь под курсором (подсветка), выбранная деталь и палитра у точки клика.
  const [hovered, setHovered] = useState(-1);
  const [selected, setSelected] = useState(-1);
  const [picker, setPicker] = useState<{ x: number; y: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<PaintJob | null>(null);
  const [busy, setBusy] = useState(false);

  // Пока сервер собирает 3MF — опрашиваем результат.
  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    const timer = setTimeout(async () => {
      const r = await fetch(`/api/v1/uploads/${uploadId}/paints/${job.id}`);
      if (r.ok) setJob((await r.json()) as PaintJob);
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [job, uploadId]);

  async function loadParts() {
    setLoading(true);
    setError(null);
    try {
      const [pr, cr] = await Promise.all([
        fetch(`/api/v1/uploads/${uploadId}/parts`),
        fetch(`/api/v1/paint/colors`),
      ]);
      if (!pr.ok || !cr.ok) {
        const bad = pr.ok ? cr : pr;
        const body = (await bad.json().catch(() => ({}))) as { detail?: string };
        throw new Error(typeof body.detail === "string" ? body.detail : `Ошибка ${bad.status}.`);
      }
      const partsBody = (await pr.json()) as PartsResponse;
      const colorsBody = (await cr.json()) as { colors: PaintColor[] };
      setParts(partsBody.parts);
      setPartsUnits(partsBody.units);
      setPalette(colorsBody.colors);
      setHist(historyStart(defaultColors(partsBody.parts, colorsBody.colors)));
      setSelected(-1);
      setPicker(null);
      setJob(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function setColor(index: number, key: string) {
    setHist((h) => historyPush(h, h.present.map((v, i) => (i === index ? key : v))));
    setJob(null);
  }

  function fillAll(key: string) {
    setHist((h) => historyPush(h, h.present.map(() => key)));
    setJob(null);
  }

  const undo = useCallback(() => {
    setHist(historyUndo);
    setJob(null);
  }, []);
  const redo = useCallback(() => {
    setHist(historyRedo);
    setJob(null);
  }, []);

  // Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y, пока открыта раскраска. В полях ввода не перехватываем.
  useEffect(() => {
    if (!parts) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setPicker(null);
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      const action = historyKey(e);
      if (!action) return;
      e.preventDefault();
      if (action === "undo") undo();
      else redo();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [parts, undo, redo]);

  function onFaceClick(face: number, x: number, y: number) {
    if (!parts) return;
    const i = partAtFace(parts, face);
    if (i < 0) return;
    setSelected(i);
    setPicker({ x, y });
  }

  function pick(key: string) {
    if (selected >= 0) setColor(selected, key);
    setPicker(null);
  }

  async function build() {
    if (!parts) return;
    const bad = validateColors(colors, parts, palette);
    if (bad) {
      setError(bad);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/v1/uploads/${uploadId}/paints`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ colors }),
      });
      if (r.status === 422) {
        const body = (await r.json().catch(() => ({}))) as {
          detail?: { errors?: { colors?: string } } | string;
        };
        if (typeof body.detail === "object" && body.detail?.errors?.colors) setError(body.detail.errors.colors);
        else setError(typeof body.detail === "string" ? body.detail : "Проверьте цвета.");
        return;
      }
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { detail?: string };
        throw new Error(typeof body.detail === "string" ? body.detail : `Ошибка ${r.status}.`);
      }
      setJob((await r.json()) as PaintJob);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Диапазоны для 3D-просмотра пересчитываем только при смене цветов — иначе сцена
  // перерисовывалась бы на каждый рендер.
  // Деталь под курсором и выбранная — светлее, чтобы было видно, что покрасится.
  const ranges = useMemo(() => {
    if (!parts) return [];
    return partRanges(parts, colors, palette).map((r, i) =>
      i === hovered || i === selected ? { ...r, hex: lighten(r.hex, i === hovered ? 0.4 : 0.25) } : r,
    );
  }, [parts, colors, palette, hovered, selected]);
  const warning = colorsWarning(colors);

  const working = busy || (job !== null && (job.status === "queued" || job.status === "running"));
  const byKey = new Map(palette.map((c) => [c.key, c]));

  return (
    <section className="flex flex-col gap-4 rounded-lg border p-6" style={BORDER}>
      <div>
        <h2 className="text-lg font-semibold">Раскраска по частям</h2>
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
          Если модель состоит из отдельных деталей (корпус и крышка, кольцо и брелок), каждую
          можно напечатать своим цветом пластика. Получится новая модель в формате 3MF, исходная
          останется как есть. Цена от количества цветов не зависит.
        </p>
      </div>

      {!parts ? (
        <div className="flex flex-wrap items-center gap-4">
          <button
            type="button"
            onClick={() => void loadParts()}
            disabled={loading}
            className="rounded-md border px-5 py-2.5 font-medium disabled:opacity-60"
            style={BORDER}
          >
            {loading ? "Разбираем…" : "Разобрать на детали"}
          </button>
          <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
            Сначала нанесите надпись или логотип, если нужно, — а раскрашивайте уже готовую модель.
          </span>
        </div>
      ) : (
        <>
          <div className="relative" style={{ cursor: hovered >= 0 ? "pointer" : undefined }}>
            <ModelViewer
              url={`/api/v1/uploads/${uploadId}/parts/file?units=${partsUnits}`}
              ext="stl"
              partColors={ranges}
              height={320}
              onFaceHover={(face) => setHovered(partAtFace(parts, face))}
              onFaceClick={onFaceClick}
            />
            {picker && selected >= 0 && palette.length > 0 && (
              <div
                role="dialog"
                aria-label={`Цвет: ${parts[selected].name}`}
                className="absolute z-10 flex w-56 flex-col gap-2 rounded-md border p-3 text-sm shadow-lg"
                style={{
                  ...FIELD,
                  background: "var(--surface-raised)",
                  // Рядом с точкой клика, но не за краем окна просмотра (ширина 224, высота ~180).
                  left: `clamp(8px, ${picker.x + 12}px, calc(100% - 232px))`,
                  top: Math.max(8, Math.min(picker.y + 12, 320 - 188)),
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{parts[selected].name}</span>
                  <button
                    type="button"
                    onClick={() => setPicker(null)}
                    aria-label="Закрыть палитру"
                    className="px-1"
                  >
                    ✕
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {palette.map((c) => (
                    <button
                      key={c.key}
                      type="button"
                      onClick={() => pick(c.key)}
                      title={c.name}
                      aria-label={c.name}
                      aria-pressed={colors[selected] === c.key}
                      className="h-8 w-8 rounded-full border-2"
                      style={{
                        background: c.hex,
                        borderColor: colors[selected] === c.key ? "var(--ink)" : "var(--ink-muted)",
                      }}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
          <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
            Нажмите на деталь в окне — рядом появится палитра. Или выберите цвет в списке ниже.
          </p>

          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="flex flex-wrap items-center gap-3">
              <span>{summaryLine(parts, colors)}</span>
              <button
                type="button"
                onClick={undo}
                disabled={hist.past.length === 0}
                className="rounded-md border px-2 py-1 disabled:opacity-40"
                style={BORDER}
                title="Ctrl+Z"
              >
                ↶ Отменить
              </button>
              <button
                type="button"
                onClick={redo}
                disabled={hist.future.length === 0}
                className="rounded-md border px-2 py-1 disabled:opacity-40"
                style={BORDER}
                title="Ctrl+Shift+Z"
              >
                ↷ Повторить
              </button>
            </span>
            {parts.length > 1 && palette.length > 0 && (
              <label className="flex items-center gap-2">
                <span style={{ color: "var(--ink-muted)" }}>Всё одним цветом:</span>
                <select
                  className="rounded-md border px-2 py-1"
                  style={FIELD}
                  value=""
                  onChange={(e) => e.target.value && fillAll(e.target.value)}
                  aria-label="Покрасить все детали одним цветом"
                >
                  <option value="">выбрать…</option>
                  {palette.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <ul className="flex flex-col divide-y" style={BORDER}>
            {parts.map((p, i) => {
              const chosen = byKey.get(colors[i] ?? "");
              return (
                <li
                  key={p.index}
                  className="flex flex-wrap items-center gap-3 px-1 py-2 text-sm"
                  style={i === selected ? { background: "var(--surface-raised)", outline: "2px solid var(--filament)" } : undefined}
                  onMouseEnter={() => setHovered(i)}
                  onMouseLeave={() => setHovered(-1)}
                >
                  <span
                    aria-hidden
                    className="inline-block h-5 w-5 shrink-0 rounded-full border"
                    style={{ background: chosen?.hex ?? "transparent", borderColor: "var(--ink-muted)" }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="font-medium">{p.name}</span>
                    <span className="ml-2" style={{ color: "var(--ink-muted)" }}>
                      {partCaption(p)}
                    </span>
                  </span>
                  <select
                    className="rounded-md border px-2 py-1"
                    style={FIELD}
                    value={colors[i] ?? ""}
                    onChange={(e) => setColor(i, e.target.value)}
                    aria-label={`Цвет: ${p.name}`}
                  >
                    {!chosen && <option value="">выберите цвет</option>}
                    {palette.map((c) => (
                      <option key={c.key} value={c.key}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </li>
              );
            })}
          </ul>

          {warning && (
            <p className="text-sm" role="status" style={{ color: "var(--accent)" }}>
              {warning}
            </p>
          )}

          {parts.length === 1 && (
            <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Модель цельная — одна деталь. Можно выбрать цвет всей модели; в несколько цветов
              печатаются только модели из отдельных деталей.
            </p>
          )}
          {parts.some((p) => p.merged > 0) && (
            <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Деталей больше, чем мы показываем отдельно: самые мелкие собраны в строку «Мелкие
              детали» и красятся одним цветом.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-4">
            <button
              type="button"
              onClick={() => void build()}
              disabled={working}
              className="rounded-md px-5 py-2.5 font-medium disabled:opacity-60"
              style={{ background: "var(--filament)", color: "var(--on-filament)" }}
            >
              {working ? "Собираем…" : "Собрать модель в цветах"}
            </button>
            {job && job.status !== "done" && (
              <span className="text-sm" aria-live="polite" style={{ color: "var(--ink-muted)" }}>
                {STATUS_TEXT[job.status]}
              </span>
            )}
          </div>
        </>
      )}

      {error && (
        <p role="alert" className="text-sm">
          {error}
        </p>
      )}
      {job?.status === "error" && (
        <p role="alert" className="text-sm">
          {job.error ?? "Не получилось собрать — попробуйте ещё раз."}
        </p>
      )}
      {job?.status === "done" && job.result_upload_id && (
        <div className="flex flex-col gap-2 rounded-md border p-4 text-sm" style={BORDER} aria-live="polite">
          <p>Готово — модель в цветах собрана.</p>
          <Link
            href={`/upload/${job.result_upload_id}`}
            className="inline-block rounded-md px-4 py-2 font-medium"
            style={{ background: "var(--filament)", color: "var(--on-filament)", width: "fit-content" }}
          >
            Открыть модель в цветах →
          </Link>
          <p style={{ color: "var(--ink-muted)" }}>
            Там же — 3D-просмотр, расчёт печати и заказ. Передумали — вернитесь сюда и выберите
            другие цвета.
          </p>
        </div>
      )}
    </section>
  );
}
