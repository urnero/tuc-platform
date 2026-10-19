"use client";

/**
 * Блок «Расчёт печати» на странице модели (B04).
 * Клиент выбирает материал и поддержки → POST /api/v1/uploads/{id}/slice →
 * пока статус queued/running, опрашиваем GET раз в 2 секунды → показываем время и граммы.
 * Цена из этих цифр появится в B05.
 */

import { useEffect, useState } from "react";
import {
  formatDuration,
  formatGrams,
  MATERIAL_LABELS,
  STATUS_TEXT,
  type SliceRecord,
} from "@/lib/slice";

const POLL_MS = 2000;

export default function SliceCalc({ uploadId }: { uploadId: string }) {
  const [materials, setMaterials] = useState<string[]>(["PLA", "PETG", "ABS"]);
  const [material, setMaterial] = useState("PLA");
  const [supports, setSupports] = useState(false);
  const [record, setRecord] = useState<SliceRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/materials")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { materials: string[] } | null) => d && setMaterials(d.materials))
      .catch(() => {});
  }, []);

  // Пока сервер считает — опрашиваем результат.
  useEffect(() => {
    if (!record || (record.status !== "queued" && record.status !== "running")) return;
    const url = `/api/v1/uploads/${uploadId}/slice?material=${record.material}&supports=${record.supports}`;
    const timer = setTimeout(async () => {
      const r = await fetch(url);
      if (r.ok) setRecord((await r.json()) as SliceRecord);
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [record, uploadId]);

  async function calculate() {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/v1/uploads/${uploadId}/slice`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ material, supports }),
      });
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `Ошибка ${r.status}.`);
      }
      setRecord((await r.json()) as SliceRecord);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const inProgress = record?.status === "queued" || record?.status === "running";
  const res = record?.status === "done" ? record.result : null;

  return (
    <section className="flex flex-col gap-4 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
      <h2 className="text-lg font-semibold">Расчёт печати</h2>

      <div className="flex flex-wrap items-end gap-4 text-sm">
        <label className="flex min-w-0 max-w-full flex-col gap-1">
          <span style={{ color: "var(--muted)" }}>Материал</span>
          <select
            value={material}
            onChange={(e) => setMaterial(e.target.value)}
            className="w-full max-w-full rounded-md border px-3 py-2"
            style={{ borderColor: "var(--muted)", background: "var(--bg)", color: "var(--fg)" }}
          >
            {materials.map((m) => (
              <option key={m} value={m}>
                {MATERIAL_LABELS[m] ?? m}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 py-2">
          <input type="checkbox" checked={supports} onChange={(e) => setSupports(e.target.checked)} />
          Нужны поддержки
        </label>
        <button
          type="button"
          onClick={() => void calculate()}
          disabled={busy || inProgress}
          className="rounded-md px-4 py-2 font-medium disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--bg)" }}
        >
          Рассчитать печать
        </button>
      </div>

      {error && <p role="alert">{error}</p>}

      {record && (
        <div className="text-sm" aria-live="polite">
          {record.status !== "done" && (
            <p>
              {STATUS_TEXT[record.status]}
              {record.status === "error" && record.error ? ` — ${record.error}` : ""}
            </p>
          )}
          {res && (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2">
              <dt style={{ color: "var(--muted)" }}>Материал</dt>
              <dd>
                {res.material}
                {res.supports ? ", с поддержками" : ""}
              </dd>
              <dt style={{ color: "var(--muted)" }}>Время печати</dt>
              <dd>{formatDuration(res.print_time_s)}</dd>
              <dt style={{ color: "var(--muted)" }}>Пластика</dt>
              <dd>{formatGrams(res.filament_g)}</dd>
              {res.layer_height_mm != null && (
                <>
                  <dt style={{ color: "var(--muted)" }}>Слой</dt>
                  <dd>{res.layer_height_mm.toString().replace(".", ",")} мм</dd>
                </>
              )}
            </dl>
          )}
        </div>
      )}
    </section>
  );
}
