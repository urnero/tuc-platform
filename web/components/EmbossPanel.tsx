"use client";

/**
 * Блок «Надпись или логотип на модели» на странице загрузки (B30).
 *
 * 1. Клиент выбирает: надпись (текст, шрифт, жирный) или логотип (SVG — грузится отдельно,
 *    POST /api/v1/uploads/{id}/logo), размер, высоту/глубину, выпуклое или углублённое,
 *    грань модели, сдвиг и поворот.
 * 2. «Нанести» → POST /api/v1/uploads/{id}/embosses → пока queued/running, опрашиваем
 *    GET раз в 2 секунды → done: ссылка на новую загрузку /upload/<result_upload_id>
 *    (копия модели с тиснением — там расчёт, цена и заказ). Исходная модель не меняется.
 */

import Link from "next/link";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import {
  DEFAULT_FORM,
  type EmbossForm,
  type EmbossJob,
  FACES,
  FONTS,
  fmt,
  LIMITS,
  STATUS_TEXT,
  STYLES,
  toParams,
  validateForm,
  validateLogoFile,
  WARNING_TEXT,
} from "@/lib/emboss";

const POLL_MS = 2000;
const BORDER = { borderColor: "var(--muted)" };
const FIELD = { borderColor: "var(--muted)", background: "var(--bg)", color: "var(--fg)" };

type Props = {
  uploadId: string;
  /** Имя загруженного логотипа (из meta загрузки), если он уже есть. */
  logoName?: string | null;
};

type Errors = Partial<Record<keyof EmbossForm, string>>;

export default function EmbossPanel({ uploadId, logoName: initialLogo = null }: Props) {
  const [form, setForm] = useState<EmbossForm>(DEFAULT_FORM);
  const [errors, setErrors] = useState<Errors>({});
  const [logoName, setLogoName] = useState<string | null>(initialLogo);
  const [logoBusy, setLogoBusy] = useState(false);
  const [job, setJob] = useState<EmbossJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // Пока сервер наносит надпись — опрашиваем результат.
  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    const timer = setTimeout(async () => {
      const r = await fetch(`/api/v1/uploads/${uploadId}/embosses/${job.id}`);
      if (r.ok) setJob((await r.json()) as EmbossJob);
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [job, uploadId]);

  function set<K extends keyof EmbossForm>(name: K, value: EmbossForm[K]) {
    setForm((f) => ({ ...f, [name]: value }));
    setErrors((e) => (e[name] ? { ...e, [name]: undefined } : e));
    setJob(null);
  }

  async function uploadLogo(file: File) {
    setError(null);
    const bad = validateLogoFile(file.name, file.size);
    if (bad) {
      setErrors((e) => ({ ...e, kind: bad }));
      return;
    }
    setLogoBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const r = await fetch(`/api/v1/uploads/${uploadId}/logo`, { method: "POST", body });
      if (!r.ok) {
        const err = (await r.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? `Ошибка ${r.status}.`);
      }
      const meta = (await r.json()) as { logo?: { name: string } };
      setLogoName(meta.logo?.name ?? file.name);
      setErrors((e) => ({ ...e, kind: undefined }));
      setJob(null);
    } catch (e) {
      setErrors((er) => ({ ...er, kind: (e as Error).message }));
    } finally {
      setLogoBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function removeLogo() {
    setLogoBusy(true);
    try {
      await fetch(`/api/v1/uploads/${uploadId}/logo`, { method: "DELETE" });
      setLogoName(null);
      setJob(null);
    } finally {
      setLogoBusy(false);
    }
  }

  async function build() {
    const found = validateForm(form, Boolean(logoName));
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/v1/uploads/${uploadId}/embosses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params: toParams(form) }),
      });
      if (r.status === 422) {
        const body = (await r.json().catch(() => ({}))) as { detail?: { errors?: Errors } | string };
        if (typeof body.detail === "object" && body.detail?.errors) setErrors(body.detail.errors);
        else setError(typeof body.detail === "string" ? body.detail : "Проверьте параметры.");
        return;
      }
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { detail?: string };
        throw new Error(typeof body.detail === "string" ? body.detail : `Ошибка ${r.status}.`);
      }
      setJob((await r.json()) as EmbossJob);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const working = busy || (job !== null && (job.status === "queued" || job.status === "running"));
  const isText = form.kind === "text";

  return (
    <section className="flex flex-col gap-4 rounded-lg border p-6" style={BORDER}>
      <div>
        <h2 className="text-lg font-semibold">Надпись или логотип на модели</h2>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Нанесём на одну из граней — выпуклыми буквами поверх модели или вырезом в ней. Получится
          новая модель, исходная останется как есть.
        </p>
      </div>

      {/* Что наносим */}
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Что нанести">
        {(
          [
            ["text", "Надпись"],
            ["logo", "Логотип (SVG)"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={form.kind === value}
            onClick={() => set("kind", value)}
            className="rounded-md border px-3 py-1.5 text-sm"
            style={form.kind === value ? { background: "var(--accent)", color: "var(--bg)", borderColor: "var(--accent)" } : BORDER}
          >
            {label}
          </button>
        ))}
      </div>

      {isText ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Надпись" error={errors.text} hint={`Кириллица и латиница, до ${LIMITS.textMaxlen} символов.`}>
            {(id) => (
              <input
                id={id}
                type="text"
                className="rounded-md border px-3 py-2"
                style={FIELD}
                value={form.text}
                maxLength={LIMITS.textMaxlen}
                onChange={(e) => set("text", e.target.value)}
              />
            )}
          </Field>
          <div className="flex flex-col gap-3">
            <Field label="Шрифт">
              {(id) => (
                <select id={id} className="rounded-md border px-3 py-2" style={FIELD} value={form.font} onChange={(e) => set("font", e.target.value as EmbossForm["font"])}>
                  {FONTS.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.bold} onChange={(e) => set("bold", e.target.checked)} />
              Жирный — прочнее и лучше читается после печати
            </label>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex flex-wrap items-center gap-3">
            {logoName ? (
              <>
                <span>
                  Логотип: <strong>{logoName}</strong>
                </span>
                <button type="button" className="underline" disabled={logoBusy} onClick={() => void removeLogo()}>
                  убрать
                </button>
              </>
            ) : (
              <span style={{ color: "var(--muted)" }}>Логотип ещё не загружен.</span>
            )}
            <label className="cursor-pointer rounded-md border px-3 py-1.5" style={BORDER}>
              {logoBusy ? "Загружаем…" : logoName ? "Заменить SVG" : "Выбрать SVG"}
              <input
                ref={fileInput}
                type="file"
                accept=".svg,image/svg+xml"
                className="sr-only"
                disabled={logoBusy}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void uploadLogo(f);
                }}
              />
            </label>
          </div>
          {errors.kind ? (
            <span role="alert">{errors.kind}</span>
          ) : (
            <span style={{ color: "var(--muted)" }}>
              SVG до 1 МБ, только контуры: текст в редакторе переведите в кривые (Inkscape: «Контур → Оконтурить объект»). Картинка
              будет одним цветом, без заливок и градиентов.
            </span>
          )}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <NumberField
          label={isText ? "Высота букв" : "Ширина логотипа"}
          unit="мм"
          value={form.size_mm}
          min={LIMITS.size.min}
          max={LIMITS.size.max}
          step={0.5}
          error={errors.size_mm}
          onChange={(v) => set("size_mm", v)}
        />
        <NumberField
          label={form.style === "engraved" ? "Глубина" : "Высота тиснения"}
          unit="мм"
          value={form.depth_mm}
          min={LIMITS.depth.min}
          max={LIMITS.depth.max}
          step={0.1}
          error={errors.depth_mm}
          onChange={(v) => set("depth_mm", v)}
        />
        <Field label="Как нанести">
          {(id) => (
            <select id={id} className="rounded-md border px-3 py-2" style={FIELD} value={form.style} onChange={(e) => set("style", e.target.value as EmbossForm["style"])}>
              {STYLES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="На какой грани" hint="Спереди — сторона, обращённая к вам в 3D-просмотре при открытии.">
          {(id) => (
            <select id={id} className="rounded-md border px-3 py-2" style={FIELD} value={form.face} onChange={(e) => set("face", e.target.value as EmbossForm["face"])}>
              {FACES.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer" style={{ color: "var(--muted)" }}>
          Сдвиг и поворот (по умолчанию — по центру грани)
        </summary>
        <div className="mt-3 grid gap-4 sm:grid-cols-3">
          <NumberField label="Сдвиг вправо" unit="мм" value={form.dx} min={-LIMITS.shift} max={LIMITS.shift} step={1} error={errors.dx} onChange={(v) => set("dx", v)} />
          <NumberField label="Сдвиг вверх" unit="мм" value={form.dy} min={-LIMITS.shift} max={LIMITS.shift} step={1} error={errors.dy} onChange={(v) => set("dy", v)} />
          <NumberField label="Поворот" unit="°" value={form.angle} min={-LIMITS.angle} max={LIMITS.angle} step={5} error={errors.angle} onChange={(v) => set("angle", v)} />
        </div>
      </details>

      <div className="flex flex-wrap items-center gap-4">
        <button
          type="button"
          onClick={() => void build()}
          disabled={working}
          className="rounded-md px-5 py-2.5 font-medium disabled:opacity-60"
          style={{ background: "var(--accent)", color: "var(--bg, #fff)" }}
        >
          {working ? "Наносим…" : "Нанести"}
        </button>
        {job && job.status !== "done" && (
          <span className="text-sm" aria-live="polite" style={{ color: "var(--muted)" }}>
            {STATUS_TEXT[job.status]}
          </span>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm">
          {error}
        </p>
      )}
      {job?.status === "error" && (
        <p role="alert" className="text-sm">
          {job.error ?? "Не получилось нанести — попробуйте другие параметры."}
        </p>
      )}
      {job?.status === "done" && job.result_upload_id && (
        <div className="flex flex-col gap-2 rounded-md border p-4 text-sm" style={BORDER} aria-live="polite">
          <p>Готово — модель с тиснением построена.</p>
          {job.warnings.map((w) => (
            <p key={w} style={{ color: "var(--muted)" }}>
              ⚠ {WARNING_TEXT[w] ?? w}
            </p>
          ))}
          <Link
            href={`/upload/${job.result_upload_id}`}
            className="inline-block rounded-md px-4 py-2 font-medium"
            style={{ background: "var(--accent)", color: "var(--bg, #fff)", width: "fit-content" }}
          >
            Открыть модель с тиснением →
          </Link>
          <p style={{ color: "var(--muted)" }}>
            Там же — 3D-просмотр, расчёт печати и заказ. Не понравилось — вернитесь сюда и
            нанесите заново с другими параметрами.
          </p>
        </div>
      )}
    </section>
  );
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm" htmlFor={id}>
      <span>{label}</span>
      {children(id)}
      {error ? (
        <span role="alert">{error}</span>
      ) : (
        hint && <span style={{ color: "var(--muted)" }}>{hint}</span>
      )}
    </label>
  );
}

function NumberField({
  label,
  unit,
  value,
  min,
  max,
  step,
  error,
  onChange,
}: {
  label: string;
  unit: string;
  value: string;
  min: number;
  max: number;
  step: number;
  error?: string;
  onChange: (v: string) => void;
}) {
  return (
    <Field label={`${label}, ${unit}`} error={error} hint={`от ${fmt(min)} до ${fmt(max)}`}>
      {(id) => (
        <input
          id={id}
          type="number"
          inputMode="decimal"
          className="rounded-md border px-3 py-2"
          style={FIELD}
          value={value}
          min={min}
          max={max}
          step={step}
          aria-invalid={error ? true : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </Field>
  );
}
