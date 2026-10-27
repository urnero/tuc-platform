"use client";

/**
 * Блок «Расчёт печати и цены» на странице модели (B04 + B05).
 *
 * 1. Клиент выбирает материал и поддержки → POST /api/v1/uploads/{id}/slice →
 *    пока статус queued/running, опрашиваем GET раз в 2 секунды → время и граммы.
 * 2. Когда расчёт печати готов → POST /api/v1/uploads/{id}/quote с тиражом,
 *    постобработкой и доставкой → цена и разложение суммы.
 *    Тираж/постобработку/доставку можно менять — цена пересчитывается без нового слайсинга.
 *    Смена материала или поддержек — заново «Рассчитать».
 * Кнопка «Оформить заказ» ведёт на форму заказа (B06): /order/new?quote=<id расчёта>.
 * Повтор заказа из кабинета (B32): `preset` — параметры прошлого заказа; с ним расчёт печати
 * запускается сам, клиенту остаётся проверить цену и нажать «Оформить заказ».
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { Preset } from "@/lib/account";
import { reachGoal } from "@/lib/metrika";
import { formatPrice } from "@/lib/format";
import {
  batchHint,
  DELIVERY_LABELS,
  optionLabel,
  POSTPROCESS_LABELS,
  type Pricing,
  type Quote,
  quoteLines,
} from "@/lib/pricing";
import {
  formatDuration,
  formatGrams,
  MATERIAL_LABELS,
  STATUS_TEXT,
  type SliceRecord,
} from "@/lib/slice";

const POLL_MS = 2000;

const selectStyle = { borderColor: "var(--muted)", background: "var(--bg)", color: "var(--fg)" };

type Props = {
  uploadId: string;
  /** Материал, выбранный заранее (модель из каталога, B20). По умолчанию PLA. */
  defaultMaterial?: string;
  /** Параметры прошлого заказа (повтор из кабинета, B32): подставляются и расчёт стартует сам. */
  preset?: Preset | null;
};

export default function SliceCalc({ uploadId, defaultMaterial = "PLA", preset = null }: Props) {
  const [materials, setMaterials] = useState<string[]>(["PLA", "PETG", "ABS"]);
  const [pricing, setPricing] = useState<Pricing | null>(null);
  const [material, setMaterial] = useState(preset?.material ?? defaultMaterial);
  const [supports, setSupports] = useState(preset?.supports ?? false);
  const [qty, setQty] = useState(preset?.qty ?? 1);
  const [postprocess, setPostprocess] = useState(preset?.postprocess ?? "none");
  const [delivery, setDelivery] = useState(preset?.delivery ?? "pickup");
  const [record, setRecord] = useState<SliceRecord | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const quoteSeq = useRef(0); // чтобы поздний ответ не перекрыл свежий

  useEffect(() => {
    fetch("/api/v1/materials")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { materials: string[] } | null) => d && setMaterials(d.materials))
      .catch(() => {});
    fetch("/api/v1/pricing")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: Pricing | null) => d && setPricing(d))
      .catch(() => {});
  }, []);

  // Повтор заказа: считаем печать сразу, не дожидаясь нажатия «Рассчитать».
  const autoStarted = useRef(false);
  useEffect(() => {
    if (!preset || autoStarted.current) return;
    autoStarted.current = true;
    void calculate();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- один раз при открытии
  }, [preset]);

  // Пока сервер считает печать — опрашиваем результат.
  useEffect(() => {
    if (!record || (record.status !== "queued" && record.status !== "running")) return;
    const url = `/api/v1/uploads/${uploadId}/slice?material=${record.material}&supports=${record.supports}`;
    const timer = setTimeout(async () => {
      const r = await fetch(url);
      if (r.ok) setRecord((await r.json()) as SliceRecord);
      // 404 — расчёта больше нет (например, поменяли единицы модели): возвращаем кнопку.
      else if (r.status === 404) setRecord(null);
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [record, uploadId]);

  // Печать посчитана (или поменяли тираж/обработку/доставку) — считаем цену.
  useEffect(() => {
    if (!record || record.status !== "done") return;
    const seq = ++quoteSeq.current;
    const body = { material: record.material, supports: record.supports, qty, postprocess, delivery };
    fetch(`/api/v1/uploads/${uploadId}/quote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(async (r) => {
        if (!r.ok) {
          const err = (await r.json().catch(() => ({}))) as { detail?: string };
          throw new Error(err.detail ?? `Ошибка ${r.status}.`);
        }
        return (await r.json()) as Quote;
      })
      .then((q) => {
        if (seq === quoteSeq.current) {
          setQuote(q);
          reachGoal("quote", uploadId);
        }
      })
      .catch((e: Error) => {
        if (seq === quoteSeq.current) setError(e.message);
      });
  }, [record, qty, postprocess, delivery, uploadId]);

  async function calculate() {
    setBusy(true);
    setError(null);
    setQuote(null);
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
  // Материал или поддержки поменяли после расчёта — цена уже не про них.
  const stale = !!res && (res.material !== material || res.supports !== supports);
  const hint = pricing ? batchHint(pricing.batch) : "";

  return (
    <section className="flex flex-col gap-4 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
      <h2 className="text-lg font-semibold">Расчёт печати и цены</h2>

      <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
        <label className="flex min-w-0 max-w-full flex-col gap-1">
          <span style={{ color: "var(--muted)" }}>Материал</span>
          <select
            value={material}
            onChange={(e) => setMaterial(e.target.value)}
            className="w-full max-w-full rounded-md border px-3 py-2"
            style={selectStyle}
          >
            {materials.map((m) => (
              <option key={m} value={m}>
                {MATERIAL_LABELS[m] ?? m}
                {pricing?.materials[m] ? ` — ${formatPrice(pricing.materials[m].price_per_g)}/г` : ""}
              </option>
            ))}
          </select>
        </label>

        <label className="flex min-w-0 max-w-full flex-col gap-1">
          <span style={{ color: "var(--muted)" }}>Тираж, шт{hint ? ` (${hint})` : ""}</span>
          <input
            type="number"
            min={1}
            max={10000}
            value={qty}
            onChange={(e) => setQty(Math.max(1, Math.min(10000, Math.round(Number(e.target.value) || 1))))}
            className="w-full max-w-full rounded-md border px-3 py-2"
            style={selectStyle}
          />
        </label>

        <label className="flex min-w-0 max-w-full flex-col gap-1">
          <span style={{ color: "var(--muted)" }}>Постобработка</span>
          <select
            value={postprocess}
            onChange={(e) => setPostprocess(e.target.value)}
            className="w-full max-w-full rounded-md border px-3 py-2"
            style={selectStyle}
          >
            {Object.entries(pricing?.postprocess ?? { none: 0 }).map(([key, price]) => (
              <option key={key} value={key}>
                {optionLabel(POSTPROCESS_LABELS, key, price, true)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex min-w-0 max-w-full flex-col gap-1">
          <span style={{ color: "var(--muted)" }}>Доставка</span>
          <select
            value={delivery}
            onChange={(e) => setDelivery(e.target.value)}
            className="w-full max-w-full rounded-md border px-3 py-2"
            style={selectStyle}
          >
            {Object.entries(pricing?.delivery ?? { pickup: 0 }).map(([key, price]) => (
              <option key={key} value={key}>
                {optionLabel(DELIVERY_LABELS, key, price, false)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-sm">
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
          {res ? "Пересчитать" : "Рассчитать цену"}
        </button>
        {stale && <span style={{ color: "var(--muted)" }}>Материал изменился — нажмите «Пересчитать».</span>}
      </div>

      {error && <p role="alert">{error}</p>}

      {record && (
        <div className="flex flex-col gap-4 text-sm" aria-live="polite">
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
          {res && !quote && !error && <p>Считаем цену…</p>}
          {res && quote && (
            <div
              className="flex flex-col gap-3 rounded-md border p-4"
              style={{ borderColor: "var(--muted)", opacity: stale ? 0.5 : 1 }}
              data-testid="quote"
            >
              <p className="text-2xl font-bold">
                {formatPrice(quote.total)}
                <span className="ml-2 text-sm font-normal" style={{ color: "var(--muted)" }}>
                  за {quote.qty} шт
                </span>
              </p>
              <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1">
                {quoteLines(quote).map((line) => (
                  <div key={line.label} className="contents">
                    <dt style={{ color: "var(--muted)" }}>{line.label}</dt>
                    <dd className="text-right">{line.value}</dd>
                  </div>
                ))}
              </dl>
              <p style={{ color: "var(--muted)" }}>
                Расчёт № <code className="break-all">{quote.id}</code>. Цены предварительные: менеджер подтвердит их при заказе.
              </p>
              {stale ? (
                <span className="text-sm" style={{ color: "var(--muted)" }}>
                  Пересчитайте цену, чтобы оформить заказ.
                </span>
              ) : (
                <Link
                  href={`/order/new?quote=${encodeURIComponent(quote.id)}`}
                  className="self-start rounded-md px-4 py-2 font-medium"
                  style={{ background: "var(--accent)", color: "var(--bg)" }}
                >
                  Оформить заказ
                </Link>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
