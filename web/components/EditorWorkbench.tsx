"use client";

/**
 * Рабочее место редактора (B21): форма по схеме параметров, кнопка «Построить», опрос сборки
 * (POST /api/v1/editors/<slug>/builds → GET …/builds/<id>), 3D-просмотр готового STL,
 * габариты и «Заказать» (POST …/builds/<id>/upload → /upload/<id>).
 *
 * При открытии строим модель с параметрами по умолчанию, чтобы клиент сразу что-то увидел.
 * Ошибки полей показываем до запроса (та же логика, что на сервере, lib/editors.ts);
 * ошибки сервера (422) раскладываем по тем же полям.
 */

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BUILD_STATUS_TEXT,
  type Build,
  type Editor,
  type EditorParam,
  type ParamValues,
  defaultValues,
  fmt,
  toRequestParams,
  validateValues,
} from "@/lib/editors";
import { formatDims, type Upload, warningText } from "@/lib/mesh";

const ModelViewer = dynamic(() => import("@/components/ModelViewer"), {
  ssr: false,
  loading: () => <ViewerBox>Загружаем 3D-просмотр…</ViewerBox>,
});

const POLL_MS = 1500;
const BORDER = { borderColor: "var(--ink-muted)" };

function ViewerBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-[420px] items-center justify-center rounded-lg border p-6 text-center" style={BORDER}>
      {children}
    </div>
  );
}

export default function EditorWorkbench({ editor }: { editor: Editor }) {
  const router = useRouter();
  const [values, setValues] = useState<ParamValues>(() => defaultValues(editor));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [build, setBuild] = useState<Build | null>(null);
  const [busy, setBusy] = useState(false); // идёт запрос или опрос сборки
  const [dirty, setDirty] = useState(false); // параметры меняли после последней сборки
  const [netError, setNetError] = useState<string | null>(null);
  const [ordering, setOrdering] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startedRef = useRef(false); // первую сборку запускаем один раз

  const stopPolling = () => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    pollTimer.current = null;
  };

  /** Ждём worker: перечитываем запись сборки, пока она queued / running. */
  const poll = useCallback(
    (record: Build) => {
      stopPolling();
      pollTimer.current = setTimeout(async () => {
        try {
          const r = await fetch(`/api/v1/editors/${editor.slug}/builds/${record.id}`);
          if (!r.ok) throw new Error(`Ошибка ${r.status}.`);
          const next = (await r.json()) as Build;
          setBuild(next);
          if (next.status === "queued" || next.status === "running") poll(next);
          else setBusy(false);
        } catch {
          setNetError("Не удалось узнать состояние сборки. Попробуйте ещё раз.");
          setBusy(false);
        }
      }, POLL_MS);
    },
    [editor.slug],
  );

  const startBuild = useCallback(
    async (current: ParamValues) => {
      const clientErrors = validateValues(editor, current);
      setErrors(clientErrors);
      if (Object.keys(clientErrors).length > 0) return;
      setBusy(true);
      setNetError(null);
      try {
        const r = await fetch(`/api/v1/editors/${editor.slug}/builds`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ params: toRequestParams(editor, current) }),
        });
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
        setBuild(record);
        setDirty(false);
        if (record.status === "queued" || record.status === "running") poll(record);
        else setBusy(false);
      } catch {
        setNetError("Не удалось связаться с сервером. Попробуйте ещё раз.");
        setBusy(false);
      }
    },
    [editor, poll],
  );

  // Первая сборка — с параметрами по умолчанию.
  useEffect(() => {
    if (!startedRef.current && editor.scad_ready) {
      startedRef.current = true;
      void startBuild(defaultValues(editor));
    }
    return stopPolling;
  }, [editor, startBuild]);

  function update(name: string, value: string | boolean) {
    const next = { ...values, [name]: value };
    setValues(next);
    setDirty(true);
    // Подсказываем сразу, но не ругаемся на поля, которых ещё не трогали.
    const all = validateValues(editor, next);
    setErrors((prev) => {
      const shown: Record<string, string> = {};
      for (const key of Object.keys(all)) if (key === name || prev[key]) shown[key] = all[key];
      return shown;
    });
  }

  async function order() {
    if (!build || build.status !== "done") return;
    setOrdering(true);
    setNetError(null);
    try {
      const r = await fetch(`/api/v1/editors/${editor.slug}/builds/${build.id}/upload`, { method: "POST" });
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

  const ready = build?.status === "done" && !!build.mesh;
  const hasErrors = Object.keys(errors).length > 0;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      {/* --- форма --- */}
      <form
        className="flex flex-col gap-4 rounded-lg border p-6"
        style={BORDER}
        onSubmit={(e) => {
          e.preventDefault();
          void startBuild(values);
        }}
        noValidate
      >
        <h2 className="text-lg font-semibold">Параметры</h2>
        {editor.params.map((p) => (
          <Field key={p.name} param={p} value={values[p.name]} error={errors[p.name]} onChange={(v) => update(p.name, v)} />
        ))}
        {!editor.scad_ready && (
          <p role="alert" className="text-sm">
            Редактор ещё настраивается — построить модель пока нельзя.
          </p>
        )}
        <button
          type="submit"
          disabled={busy || hasErrors || !editor.scad_ready}
          className="rounded-md px-5 py-2.5 font-medium disabled:opacity-60"
          style={{ background: "var(--filament)", color: "var(--on-filament)" }}
        >
          {busy ? BUILD_STATUS_TEXT[build?.status ?? "queued"] : dirty || !build ? "Построить модель" : "Модель построена"}
        </button>
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Размеры в мм. Модель строится на сервере — обычно за несколько секунд.
        </p>
      </form>

      {/* --- просмотр и заказ --- */}
      <section className="flex flex-col gap-4">
        {ready ? (
          <ModelViewer key={build.id} url={build.file_url} ext="stl" />
        ) : (
          <ViewerBox>
            {build?.status === "error" ? (
              <span role="alert">{build.error ?? BUILD_STATUS_TEXT.error}</span>
            ) : busy ? (
              BUILD_STATUS_TEXT[build?.status ?? "queued"]
            ) : (
              "Задайте параметры и нажмите «Построить модель»."
            )}
          </ViewerBox>
        )}

        <div className="flex flex-col gap-4 rounded-lg border p-6" style={BORDER}>
          {ready && build.mesh ? (
            <>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                <dt style={{ color: "var(--ink-muted)" }}>Габариты</dt>
                <dd>{formatDims(build.mesh.bbox_mm, "mm")}</dd>
                <dt style={{ color: "var(--ink-muted)" }}>Объём</dt>
                <dd>{fmt(build.mesh.volume_cm3)} см³</dd>
                <dt style={{ color: "var(--ink-muted)" }}>Материал по умолчанию</dt>
                <dd>{editor.material} — можно поменять при расчёте</dd>
              </dl>
              {build.mesh.warnings.length > 0 && (
                <ul className="flex flex-col gap-1 text-sm">
                  {build.mesh.warnings.map((w) => (
                    <li key={w}>⚠ {warningText(w)}</li>
                  ))}
                </ul>
              )}
              {dirty && (
                <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
                  Параметры изменились — нажмите «Построить модель», чтобы увидеть новую версию.
                </p>
              )}
            </>
          ) : (
            <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Габариты и объём появятся, когда модель построится.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-4 pt-2">
            <button
              type="button"
              onClick={() => void order()}
              disabled={!ready || dirty || busy || ordering}
              className="rounded-md px-5 py-2.5 font-medium disabled:opacity-60"
              style={{ background: "var(--filament)", color: "var(--on-filament)" }}
            >
              {ordering ? "Готовим…" : "Заказать"}
            </button>
            <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Дальше — расчёт печати, цена и оформление заказа.
            </span>
          </div>
          {netError && (
            <p role="alert" className="text-sm">
              {netError}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

/** Одно поле формы по типу параметра: число, галочка, список, текст. */
function Field({
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
  const errorId = `${id}-error`;
  const common = {
    id,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? errorId : undefined,
    className: "w-full max-w-full rounded-md border bg-transparent px-3 py-2",
    style: { borderColor: error ? "var(--filament-text)" : "var(--ink-muted)" },
  };

  if (param.type === "bool") {
    return (
      <label className="flex min-w-0 flex-col gap-1 text-sm">
        <span className="flex items-center gap-2">
          <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
          {param.label}
        </span>
        {param.hint && <span style={{ color: "var(--ink-muted)" }}>{param.hint}</span>}
      </label>
    );
  }

  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm" htmlFor={id}>
      <span>
        {param.label}
        {param.unit && <span style={{ color: "var(--ink-muted)" }}>, {param.unit}</span>}
      </span>
      {param.type === "choice" ? (
        <select {...common} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {param.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ) : param.type === "number" ? (
        <input
          {...common}
          type="number"
          inputMode="decimal"
          value={String(value ?? "")}
          min={param.min ?? undefined}
          max={param.max ?? undefined}
          step={param.step ?? (param.integer ? 1 : "any")}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          {...common}
          type="text"
          value={String(value ?? "")}
          maxLength={param.maxlen}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {param.type === "number" && (param.min !== null || param.max !== null) && !error && (
        <span style={{ color: "var(--ink-muted)" }}>
          {param.min !== null && param.max !== null
            ? `от ${fmt(param.min)} до ${fmt(param.max)}`
            : param.min !== null
              ? `не меньше ${fmt(param.min)}`
              : `не больше ${fmt(param.max as number)}`}
          {param.hint ? ` · ${param.hint}` : ""}
        </span>
      )}
      {param.type !== "number" && param.hint && !error && <span style={{ color: "var(--ink-muted)" }}>{param.hint}</span>}
      {error && (
        <span id={errorId} role="alert">
          {error}
        </span>
      )}
    </label>
  );
}
