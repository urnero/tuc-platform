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
 * UX (B42): индикатор шагов расчёта с таймером, подсказка «когда какой материал», ошибки
 * человеческим языком (lib/errors.ts), на телефоне — липкая панель «цена + Оформить» внизу экрана.
 * Материалы (B44): список и подсказки — из справочника (GET /api/v1/materials, config/materials.yaml).
 * Смолы (SLA) — «цена по запросу»: вместо расчёта форма заявки (LeadForm), оплаты нет.
 */

import Link from "next/link";
import LeadForm from "@/components/LeadForm";
import { useEffect, useRef, useState } from "react";
import type { Preset } from "@/lib/account";
import { caughtErrorText, responseErrorText, sliceErrorText } from "@/lib/errors";
import { reachGoal } from "@/lib/metrika";
import { formatPrice } from "@/lib/format";
import { FALLBACK_MATERIALS, materialHint, materialOptionLabel, type MaterialsResponse } from "@/lib/materials";
import {
  batchHint,
  clientPerGram,
  DELIVERY_LABELS,
  formatPerGram,
  optionLabel,
  POSTPROCESS_LABELS,
  type Pricing,
  type Quote,
  quoteLines,
} from "@/lib/pricing";
import {
  formatDuration,
  formatElapsed,
  formatGrams,
  MATERIAL_HINTS,
  MATERIAL_LABELS,
  type SliceRecord,
  sliceSteps,
  SUPPORTS_AUTO_TEXT,
  SUPPORTS_DEFAULT,
  SUPPORTS_OFF_TEXT,
  supportsNote,
} from "@/lib/slice";

const POLL_MS = 2000;

const selectStyle = { borderColor: "var(--ink-muted)", background: "var(--surface)", color: "var(--ink)" };

type Props = {
  uploadId: string;
  /** Материал, выбранный заранее (модель из каталога, B20). По умолчанию PLA. */
  defaultMaterial?: string;
  /** Параметры прошлого заказа (повтор из кабинета, B32): подставляются и расчёт стартует сам. */
  preset?: Preset | null;
};

export default function SliceCalc({ uploadId, defaultMaterial = "PLA", preset = null }: Props) {
  const [catalog, setCatalog] = useState<MaterialsResponse>(FALLBACK_MATERIALS);
  const [pricing, setPricing] = useState<Pricing | null>(null);
  const [material, setMaterial] = useState(preset?.material ?? defaultMaterial);
  const [supports, setSupports] = useState(preset?.supports ?? SUPPORTS_DEFAULT);
  const [qty, setQty] = useState(preset?.qty ?? 1);
  const [postprocess, setPostprocess] = useState(preset?.postprocess ?? "none");
  const [delivery, setDelivery] = useState(preset?.delivery ?? "pickup");
  const [record, setRecord] = useState<SliceRecord | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const quoteSeq = useRef(0); // чтобы поздний ответ не перекрыл свежий
  const [startedAt, setStartedAt] = useState<number | null>(null); // для «идёт 12 с»
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    fetch("/api/v1/materials")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: MaterialsResponse | null) => d && setCatalog(d))
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
      // Сеть моргнула — не страшно: следующий опрос будет через 2 с (меняем record, чтобы эффект перезапустился).
      const r = await fetch(url).catch(() => null);
      if (!r) setRecord((rec) => (rec ? { ...rec } : rec));
      else if (r.ok) setRecord((await r.json()) as SliceRecord);
      // 404 — расчёта больше нет (например, поменяли единицы модели): возвращаем кнопку.
      else if (r.status === 404) setRecord(null);
      else setRecord((rec) => (rec ? { ...rec } : rec));
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
        if (!r.ok) throw new Error(await responseErrorText(r));
        return (await r.json()) as Quote;
      })
      .then((q) => {
        if (seq === quoteSeq.current) {
          setQuote(q);
          reachGoal("quote", uploadId);
        }
      })
      .catch((e: unknown) => {
        if (seq === quoteSeq.current) setError(caughtErrorText(e));
      });
  }, [record, qty, postprocess, delivery, uploadId]);

  async function calculate() {
    setBusy(true);
    setError(null);
    setQuote(null);
    setStartedAt(Date.now());
    try {
      const r = await fetch(`/api/v1/uploads/${uploadId}/slice`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ material, supports }),
      });
      if (!r.ok) throw new Error(await responseErrorText(r));
      setRecord((await r.json()) as SliceRecord);
    } catch (e) {
      setError(caughtErrorText(e));
    } finally {
      setBusy(false);
    }
  }

  const inProgress = record?.status === "queued" || record?.status === "running";
  const res = record?.status === "done" ? record.result : null;
  // Материал или поддержки поменяли после расчёта — цена уже не про них.
  const stale = !!res && (res.material !== material || res.supports !== supports);
  const hint = pricing ? batchHint(pricing.batch) : "";
  // Смола (SLA) — цена по запросу: показываем заявку вместо расчёта.
  const onRequest = (catalog.on_request ?? []).includes(material);
  const materialItem = catalog.items?.find((i) => i.key === material);
  const materialText = materialHint(material, catalog.items, MATERIAL_HINTS);
  // Цена есть и актуальна — можно оформлять (кнопка в блоке и липкая панель на телефоне).
  const canOrder = !!res && !!quote && !stale;
  const orderHref = quote ? `/order/new?quote=${encodeURIComponent(quote.id)}` : "";
  const showProgress = !!record && (inProgress || record.status === "error" || (record.status === "done" && !quote && !error));

  // Пока идёт расчёт — тикаем раз в секунду для строки «идёт 12 с».
  useEffect(() => {
    if (!showProgress) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [showProgress]);

  return (
    <section className="flex flex-col gap-4 rounded-lg border p-6" style={{ borderColor: "var(--ink-muted)" }}>
      <h2 className="text-lg font-semibold">Расчёт печати и цены</h2>

      <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
        <label className="flex min-w-0 max-w-full flex-col gap-1">
          <span style={{ color: "var(--ink-muted)" }}>Материал</span>
          <select
            value={material}
            onChange={(e) => setMaterial(e.target.value)}
            className="w-full max-w-full rounded-md border px-3 py-2"
            style={selectStyle}
          >
            <optgroup label="Пластик — цена сразу">
              {catalog.materials.map((m) => (
                <option key={m} value={m}>
                  {catalog.items?.length ? materialOptionLabel(m, catalog.items) : (MATERIAL_LABELS[m] ?? m)}
                  {perGramSuffix(pricing, m)}
                </option>
              ))}
            </optgroup>
            {(catalog.on_request ?? []).length > 0 && (
              <optgroup label="Смола (SLA) — цена по запросу">
                {(catalog.on_request ?? []).map((m) => (
                  <option key={m} value={m}>
                    {materialOptionLabel(m, catalog.items)}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          {materialText && (
            <span className="text-xs leading-snug" style={{ color: "var(--ink-muted)" }} data-testid="material-hint">
              {materialText}
              {materialItem?.needs_enclosure ? " Печатаем в закрытой камере." : ""}
            </span>
          )}
        </label>

        <label className="flex min-w-0 max-w-full flex-col gap-1">
          <span style={{ color: "var(--ink-muted)" }}>Тираж, шт{hint ? ` (${hint})` : ""}</span>
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

        {!onRequest && (
          <>
            <label className="flex min-w-0 max-w-full flex-col gap-1">
              <span style={{ color: "var(--ink-muted)" }}>Постобработка</span>
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
              <span style={{ color: "var(--ink-muted)" }}>Доставка</span>
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
          </>
        )}
      </div>

      {onRequest && (
        <LeadForm
          key={material}
          uploadId={uploadId}
          material={material}
          materialName={materialItem?.name ?? material}
          qty={qty}
        />
      )}

      {!onRequest && (
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <details className="w-full" style={{ color: "var(--ink-muted)" }}>
            <summary className="cursor-pointer py-2">
              {supports ? SUPPORTS_AUTO_TEXT : SUPPORTS_OFF_TEXT} · для опытных
            </summary>
            <label className="flex items-center gap-2 py-2" style={{ color: "var(--ink)" }}>
              <input type="checkbox" checked={!supports} onChange={(e) => setSupports(!e.target.checked)} />
              Печатать без поддержек (я знаю, что нависаний нет)
            </label>
          </details>
          <button
            type="button"
            onClick={() => void calculate()}
            disabled={busy || inProgress}
            className="rounded-md px-4 py-2 font-medium disabled:opacity-50"
            style={{ background: "var(--filament)", color: "var(--on-filament)" }}
          >
            {res ? "Пересчитать" : "Рассчитать цену"}
          </button>
          {stale && <span style={{ color: "var(--ink-muted)" }}>Материал изменился — нажмите «Пересчитать».</span>}
        </div>
      )}

      {error && (
        <p role="alert" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}

      {record && !onRequest && (
        <div className="flex flex-col gap-4 text-sm" aria-live="polite">
          {showProgress && (
            <SliceProgress
              record={record}
              hasQuote={!!quote}
              elapsed={startedAt ? (now - startedAt) / 1000 : null}
            />
          )}
          {res && (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2">
              <dt style={{ color: "var(--ink-muted)" }}>Материал</dt>
              <dd>
                {res.material}
                {supportsNote(res)}
              </dd>
              <dt style={{ color: "var(--ink-muted)" }}>Время печати</dt>
              <dd>{formatDuration(res.print_time_s)}</dd>
              <dt style={{ color: "var(--ink-muted)" }}>Пластика</dt>
              <dd>{formatGrams(res.filament_g)}</dd>
              {res.layer_height_mm != null && (
                <>
                  <dt style={{ color: "var(--ink-muted)" }}>Слой</dt>
                  <dd>{res.layer_height_mm.toString().replace(".", ",")} мм</dd>
                </>
              )}
            </dl>
          )}
          {res && quote && (
            <div
              className="flex flex-col gap-3 rounded-md border p-4"
              style={{ borderColor: "var(--ink-muted)", opacity: stale ? 0.5 : 1 }}
              data-testid="quote"
            >
              <p className="text-2xl font-bold">
                {formatPrice(quote.total)}
                <span className="ml-2 text-sm font-normal" style={{ color: "var(--ink-muted)" }}>
                  за {quote.qty} шт
                </span>
              </p>
              <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1">
                {quoteLines(quote).map((line) => (
                  <div key={line.label} className="contents">
                    <dt style={{ color: "var(--ink-muted)" }}>{line.label}</dt>
                    <dd className="text-right">{line.value}</dd>
                  </div>
                ))}
              </dl>
              <p style={{ color: "var(--ink-muted)" }}>
                Расчёт № <code className="break-all">{quote.id}</code>. Цены предварительные: менеджер подтвердит их при заказе.
              </p>
              {stale ? (
                <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
                  Пересчитайте цену, чтобы оформить заказ.
                </span>
              ) : (
                <Link href={orderHref} className="btn btn-primary self-start">
                  Оформить заказ
                </Link>
              )}
            </div>
          )}
        </div>
      )}

      {canOrder && quote && (
        <>
          {/* Место под липкую панель, чтобы она не закрывала низ страницы на телефоне. */}
          <div className="h-16 sm:hidden" aria-hidden />
          <div
            className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-between gap-3 border-t px-4 py-3 sm:hidden"
            style={{
              background: "var(--surface-raised)",
              borderColor: "var(--line)",
              paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))",
            }}
            data-testid="sticky-order"
          >
            <div className="min-w-0 leading-tight">
              <p className="text-lg font-bold">{formatPrice(quote.total)}</p>
              <p className="truncate text-xs" style={{ color: "var(--ink-muted)" }}>
                {quote.material}, {quote.qty} шт
              </p>
            </div>
            <Link href={orderHref} className="btn btn-primary shrink-0">
              Оформить
            </Link>
          </div>
        </>
      )}
    </section>
  );
}

/** Индикатор шагов расчёта (B42): что сейчас делает сервер и сколько уже ждём. */
function SliceProgress({ record, hasQuote, elapsed }: { record: SliceRecord; hasQuote: boolean; elapsed: number | null }) {
  const failed = record.status === "error";
  const steps = sliceSteps(record.status, hasQuote);
  return (
    <div className="flex flex-col gap-3" data-testid="slice-progress">
      <ol className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-4">
        {steps.map((step, i) => {
          const color =
            step.state === "done" ? "var(--ink)" : step.state === "active" ? (failed ? "var(--danger)" : "var(--filament-text)") : "var(--ink-muted)";
          return (
            <li key={step.label} className="flex items-center gap-2" style={{ color }} aria-current={step.state === "active" ? "step" : undefined}>
              <span
                className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold"
                style={{
                  borderColor: step.state === "todo" ? "var(--line)" : color,
                  background: step.state === "done" ? "var(--ink)" : "transparent",
                  color: step.state === "done" ? "var(--surface-raised)" : color,
                }}
                aria-hidden
              >
                {step.state === "done" ? "✓" : failed && step.state === "active" ? "!" : i + 1}
              </span>
              <span className={step.state === "active" && !failed ? "font-semibold" : undefined}>{step.label}</span>
              {step.state === "active" && !failed && <span className="inline-block h-2 w-2 animate-pulse rounded-full" style={{ background: "var(--filament)" }} aria-hidden />}
            </li>
          );
        })}
      </ol>
      {failed ? (
        <p role="alert" style={{ color: "var(--danger)" }}>
          {sliceErrorText(record.error)}{" "}
          <Link href="/contacts" className="underline underline-offset-2">
            Связаться с нами
          </Link>
        </p>
      ) : (
        <p style={{ color: "var(--ink-muted)" }}>
          Обычно расчёт занимает 10–60 секунд: сервер нарезает модель на слои так же, как перед настоящей печатью.
          {elapsed != null && elapsed >= 1 ? ` Идёт ${formatElapsed(elapsed)}.` : ""}
        </p>
      )}
    </div>
  );
}

/** « — от 3,2 ₽/г» в списке материалов: грамм с наценкой, без часа принтера. */
function perGramSuffix(pricing: Pricing | null, material: string): string {
  const perG = pricing ? clientPerGram(pricing, material) : null;
  return perG === null ? "" : ` — от ${formatPerGram(perG)}/г`;
}
