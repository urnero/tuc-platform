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
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  defaultColors,
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
  const [colors, setColors] = useState<string[]>([]);
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
      setColors(defaultColors(partsBody.parts, colorsBody.colors));
      setJob(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function setColor(index: number, key: string) {
    setColors((c) => c.map((v, i) => (i === index ? key : v)));
    setJob(null);
  }

  function fillAll(key: string) {
    setColors((c) => c.map(() => key));
    setJob(null);
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
  const ranges = useMemo(
    () => (parts ? partRanges(parts, colors, palette) : []),
    [parts, colors, palette],
  );

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
          <ModelViewer
            url={`/api/v1/uploads/${uploadId}/parts/file?units=${partsUnits}`}
            ext="stl"
            partColors={ranges}
            height={320}
          />

          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <span>{summaryLine(parts, colors)}</span>
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
                <li key={p.index} className="flex flex-wrap items-center gap-3 py-2 text-sm">
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
