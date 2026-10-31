"use client";

/**
 * Рабочее место редактора (B21, B43): форма по схеме параметров, опрос сборки
 * (POST /api/v1/editors/<slug>/builds → GET …/builds/<id>), 3D-просмотр готового STL,
 * габариты и «Заказать» (POST …/builds/<id>/upload → /upload/<id>).
 *
 * При открытии строим модель с параметрами по умолчанию, чтобы клиент сразу что-то увидел.
 * Дальше превью пересобирается само через AUTO_BUILD_MS (300 мс) после правки — без кнопки (B67);
 * пока строится новая версия, видна прошлая с плашкой «Обновляем превью…». Новая правка
 * отменяет прошлый запрос (AbortController) и отбрасывает ответы по устаревшим сборкам (seqRef).
 * «Заказать» доступна только когда превью совпадает с формой.
 * Ошибки полей показываем до запроса (та же логика, что на сервере, lib/editors.ts);
 * ошибки сервера (422) раскладываем по тем же полям.
 */

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AUTO_BUILD_MS,
  BUILD_STATUS_TEXT,
  type Build,
  type Editor,
  type EditorParam,
  type ParamValues,
  defaultValues,
  fmt,
  hasSlider,
  parseNumber,
  rangeHint,
  sameParams,
  sliderStep,
  toRequestParams,
  validateValues,
  valueWithUnit,
} from "@/lib/editors";
import { formatDims, type Upload, warningText } from "@/lib/mesh";
import { buttonClass } from "@/lib/ui";

type RequestParams = ReturnType<typeof toRequestParams>;

const ModelViewer = dynamic(() => import("@/components/ModelViewer"), {
  ssr: false,
  loading: () => <ViewerBox>Загружаем 3D-просмотр…</ViewerBox>,
});

const POLL_MS = 1500;

/** Ошибка от abort() — мы сами отменили устаревший запрос. */
function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}
function ViewerBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-[420px] items-center justify-center rounded-[var(--radius-md)] p-6 text-center" style={{ background: "var(--sand)", color: "var(--ink-muted)" }}>
      {children}
    </div>
  );
}

export default function EditorWorkbench({ editor }: { editor: Editor }) {
  const router = useRouter();
  const [values, setValues] = useState<ParamValues>(() => defaultValues(editor));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [build, setBuild] = useState<Build | null>(null); // последняя запущенная сборка
  // Последняя готовая сборка и параметры, с которыми её просили: её и показываем, пока строится новая.
  const [shown, setShown] = useState<{ build: Build; params: RequestParams } | null>(null);
  const [busy, setBusy] = useState(false); // идёт запрос или опрос сборки
  const [netError, setNetError] = useState<string | null>(null);
  const [ordering, setOrdering] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startedRef = useRef(false); // первую сборку запускаем один раз
  const seqRef = useRef(0); // номер последней сборки: ответы по старым сборкам игнорируем
  const requestedRef = useRef<RequestParams | null>(null); // с чем просили последнюю сборку
  const abortRef = useRef<AbortController | null>(null); // текущий запрос к серверу — отменяем при новой правке

  /** Останавливаем опрос и обрываем запрос, который ещё в пути (его ответ уже не нужен). */
  const stopPolling = () => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    pollTimer.current = null;
    abortRef.current?.abort();
    abortRef.current = null;
  };

  /** Новый «пульт отмены» для очередного запроса. */
  const nextSignal = () => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    return abortRef.current.signal;
  };

  /** Сборка закончилась (готово или ошибка) — показываем, если она всё ещё последняя. */
  const finish = useCallback((record: Build, params: RequestParams) => {
    setBusy(false);
    if (record.status === "done" && record.mesh) setShown({ build: record, params });
  }, []);

  /** Ждём worker: перечитываем запись сборки, пока она queued / running. */
  const poll = useCallback(
    (record: Build, params: RequestParams, seq: number) => {
      stopPolling();
      pollTimer.current = setTimeout(async () => {
        try {
          const r = await fetch(`/api/v1/editors/${editor.slug}/builds/${record.id}`, { signal: nextSignal() });
          if (!r.ok) throw new Error(`Ошибка ${r.status}.`);
          const next = (await r.json()) as Build;
          if (seq !== seqRef.current) return; // параметры уже поменяли — эта сборка не нужна
          setBuild(next);
          if (next.status === "queued" || next.status === "running") poll(next, params, seq);
          else finish(next, params);
        } catch (e) {
          if (seq !== seqRef.current || isAbort(e)) return; // запрос отменили сами — это не ошибка
          setNetError("Не удалось узнать состояние сборки. Попробуйте ещё раз.");
          setBusy(false);
        }
      }, POLL_MS);
    },
    [editor.slug, finish],
  );

  const startBuild = useCallback(
    async (current: ParamValues) => {
      const clientErrors = validateValues(editor, current);
      setErrors(clientErrors);
      if (Object.keys(clientErrors).length > 0) return;
      const params = toRequestParams(editor, current);
      const seq = ++seqRef.current;
      requestedRef.current = params;
      stopPolling();
      setBusy(true);
      setNetError(null);
      try {
        const r = await fetch(`/api/v1/editors/${editor.slug}/builds`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ params }),
          signal: nextSignal(),
        });
        if (seq !== seqRef.current) return;
        if (r.status === 422) {
          const detail = (await r.json().catch(() => null))?.detail;
          setErrors(detail?.errors ?? { [editor.params[0].name]: "Проверьте параметры." });
          setBusy(false);
          return;
        }
        if (!r.ok) {
          const detail = (await r.json().catch(() => null))?.detail;
          setNetError(typeof detail === "string" ? detail : `Ошибка сервера (${r.status}).`);
          setBusy(false);
          return;
        }
        const record = (await r.json()) as Build;
        if (seq !== seqRef.current) return;
        setBuild(record);
        if (record.status === "queued" || record.status === "running") poll(record, params, seq);
        else finish(record, params);
      } catch (e) {
        if (seq !== seqRef.current || isAbort(e)) return; // запрос отменили сами — это не ошибка
        setNetError("Не удалось связаться с сервером. Попробуйте ещё раз.");
        setBusy(false);
      }
    },
    [editor, poll, finish],
  );

  // Первая сборка — с параметрами по умолчанию.
  useEffect(() => {
    if (!startedRef.current && editor.scad_ready) {
      startedRef.current = true;
      void startBuild(defaultValues(editor));
    }
    return () => {
      stopPolling();
      startedRef.current = false; // при повторном монтировании (dev-режим React) — строим заново
    };
  }, [editor, startBuild]);

  // Превью обновляется само: через AUTO_BUILD_MS после последней правки, если поля в порядке
  // и с такими параметрами ещё не строили. Кнопки «Обновить» нет (B67).
  useEffect(() => {
    if (!startedRef.current || !editor.scad_ready) return;
    if (Object.keys(validateValues(editor, values)).length > 0) return;
    if (sameParams(requestedRef.current, toRequestParams(editor, values))) return;
    const t = setTimeout(() => void startBuild(values), AUTO_BUILD_MS);
    return () => clearTimeout(t);
  }, [editor, values, startBuild]);

  function update(name: string, value: string | boolean) {
    const next = { ...values, [name]: value };
    setValues(next);
    // Подсказываем сразу, но не ругаемся на поля, которых ещё не трогали.
    const all = validateValues(editor, next);
    setErrors((prev) => {
      const shownErrors: Record<string, string> = {};
      for (const key of Object.keys(all)) if (key === name || prev[key]) shownErrors[key] = all[key];
      return shownErrors;
    });
  }

  async function order() {
    if (!shown || dirty) return;
    setOrdering(true);
    setNetError(null);
    try {
      const r = await fetch(`/api/v1/editors/${editor.slug}/builds/${shown.build.id}/upload`, { method: "POST" });
      if (!r.ok) {
        const detail = (await r.json().catch(() => null))?.detail;
        setNetError(typeof detail === "string" ? detail : `Ошибка сервера (${r.status}).`);
        return;
      }
      const upload = (await r.json()) as Upload;
      router.push(`/upload/${upload.id}`);
    } catch {
      setNetError("Не удалось связаться с сервером. Попробуйте ещё раз.");
    } finally {
      setOrdering(false);
    }
  }

  const hasErrors = Object.keys(errors).length > 0;
  // Показанная модель не совпадает с тем, что сейчас в форме.
  const dirty = !shown || !sameParams(shown.params, hasErrors ? {} : toRequestParams(editor, values));
  const mesh = shown?.build.mesh ?? null;
  const failed = !busy && build?.status === "error";

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
      {/* --- форма --- */}
      <form className="card flex flex-col gap-5" onSubmit={(e) => e.preventDefault()} noValidate>
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-semibold">Параметры</h2>
          <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
            Двигайте ползунки — модель справа меняется сразу.
          </p>
        </div>
        {editor.params.map((p) => (
          <ParamField key={p.name} param={p} value={values[p.name]} error={errors[p.name]} onChange={(v) => update(p.name, v)} />
        ))}
        {!editor.scad_ready && (
          <p role="alert" className="text-sm">
            Редактор ещё настраивается — построить модель пока нельзя.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={buttonClass("ghost", "sm")}
            onClick={() => {
              setValues(defaultValues(editor));
              setErrors({});
            }}
          >
            Вернуть как было
          </button>
        </div>
      </form>

      {/* --- просмотр и заказ (на телефоне — над формой, чтобы видеть, как меняется модель) --- */}
      <section className="order-first flex flex-col gap-4 lg:sticky lg:top-24 lg:order-none">
        <div className="relative">
          {shown ? (
            <ModelViewer key={shown.build.id} url={shown.build.file_url} ext="stl" />
          ) : (
            <ViewerBox>
              {failed ? (
                <span role="alert">{build?.error ?? BUILD_STATUS_TEXT.error}</span>
              ) : busy ? (
                BUILD_STATUS_TEXT[build?.status ?? "queued"]
              ) : (
                "Задайте параметры — модель построится сама."
              )}
            </ViewerBox>
          )}
          {shown && (busy || dirty || failed) && (
            <span
              className={`badge ${failed ? "badge-danger" : "badge-active"} absolute left-3 top-3`}
              role="status"
              aria-live="polite"
            >
              {failed ? "Не удалось обновить — показана прошлая версия" : busy ? "Обновляем превью…" : "Параметры изменились"}
            </span>
          )}
        </div>

        <div className="card flex flex-col gap-4">
          {mesh ? (
            <>
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
                <dt style={{ color: "var(--ink-muted)" }}>Габариты</dt>
                <dd>{formatDims(mesh.bbox_mm, "mm")}</dd>
                <dt style={{ color: "var(--ink-muted)" }}>Объём</dt>
                <dd>{fmt(mesh.volume_cm3)} см³</dd>
                <dt style={{ color: "var(--ink-muted)" }}>Материал</dt>
                <dd>{editor.material} — можно поменять при расчёте</dd>
              </dl>
              {mesh.warnings.length > 0 && (
                <ul className="flex flex-col gap-1 text-sm">
                  {mesh.warnings.map((w) => (
                    <li key={w}>⚠ {warningText(w)}</li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Габариты и объём появятся, когда модель построится.
            </p>
          )}
          {failed && shown && build?.error && (
            <p role="alert" className="text-sm" style={{ color: "var(--danger)" }}>
              {build.error}
            </p>
          )}
          <div className="flex flex-col gap-2 pt-1">
            <button
              type="button"
              onClick={() => void order()}
              disabled={!shown || dirty || busy || ordering}
              className={buttonClass("primary", "md", "w-full sm:w-fit")}
            >
              {ordering ? "Готовим…" : hasErrors ? "Исправьте размеры" : dirty && shown ? "Дождитесь обновления…" : "Заказать"}
            </button>
            <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Дальше — материал, количество и цена сразу.
            </span>
          </div>
          {netError && (
            <p role="alert" className="text-sm" style={{ color: "var(--danger)" }}>
              {netError}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

/** Одно поле формы по типу параметра: число (+ ползунок, если есть обе границы), галочка, список, текст. */
function ParamField({
  param,
  value,
  error,
  onChange,
}: {
  param: EditorParam;
  value: string | boolean | undefined;
  error?: string;
  onChange: (v: string | boolean) => void;
}) {
  const id = `param-${param.name}`;
  // Диапазон и зачем параметр (hint из editor.yaml): «от 1 до 195 мм · Под винт М8 обычно 8,5 мм.»
  const hint = rangeHint(param);
  const noteId = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  const common = {
    id,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": noteId,
    className: "field",
  };
  const note = error ? (
    <span id={`${id}-error`} role="alert" className="text-sm" style={{ color: "var(--danger)" }}>
      {error}
    </span>
  ) : hint ? (
    <span id={`${id}-hint`} className="text-sm" style={{ color: "var(--ink-muted)" }}>
      {hint}
    </span>
  ) : null;

  if (param.type === "bool") {
    return (
      <div className="flex min-w-0 flex-col gap-1">
        <label htmlFor={id} className="flex min-h-11 cursor-pointer items-center gap-3 text-sm font-semibold">
          <input
            id={id}
            type="checkbox"
            className="h-5 w-5 accent-[var(--filament)]"
            checked={Boolean(value)}
            aria-describedby={noteId}
            onChange={(e) => onChange(e.target.checked)}
          />
          {param.label}
        </label>
        {note}
      </div>
    );
  }

  const label = (
    <label htmlFor={id} className="text-sm font-semibold">
      {param.label}
      {param.unit && <span style={{ color: "var(--ink-muted)", fontWeight: 400 }}>, {param.unit}</span>}
    </label>
  );

  if (param.type === "choice") {
    return (
      <div className="flex min-w-0 flex-col gap-1">
        {label}
        <select {...common} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {param.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {note}
      </div>
    );
  }

  if (param.type === "number") {
    const n = parseNumber(String(value ?? ""));
    const slider = hasSlider(param);
    return (
      <div className="flex min-w-0 flex-col gap-1">
        {label}
        <div className="flex items-center gap-3">
          {slider && (
            <input
              type="range"
              aria-label={`${param.label} — ползунок`}
              aria-valuetext={valueWithUnit(param, value)}
              className="min-w-0 flex-1 accent-[var(--filament)]"
              min={param.min as number}
              max={param.max as number}
              step={sliderStep(param)}
              value={Number.isFinite(n) ? Math.min(Math.max(n, param.min as number), param.max as number) : (param.min as number)}
              onChange={(e) => onChange(e.target.value)}
            />
          )}
          <input
            {...common}
            className={slider ? "field !w-24 shrink-0 text-right" : "field"}
            type="number"
            inputMode="decimal"
            value={String(value ?? "")}
            min={param.min ?? undefined}
            max={param.max ?? undefined}
            step={param.step ?? (param.integer ? 1 : "any")}
            onChange={(e) => onChange(e.target.value)}
          />
          {param.unit && (
            <span aria-hidden className="w-6 shrink-0 text-sm" style={{ color: "var(--ink-muted)" }}>
              {param.unit}
            </span>
          )}
        </div>
        {note}
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-1">
      {label}
      <input {...common} type="text" value={String(value ?? "")} maxLength={param.maxlen} onChange={(e) => onChange(e.target.value)} />
      {note}
    </div>
  );
}
