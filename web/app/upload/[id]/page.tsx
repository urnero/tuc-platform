"use client";

/**
 * Страница загруженной модели (B03): 3D-просмотр, габариты, объём, предупреждения,
 * переключатель «файл в мм / в дюймах» (сохраняется на сервере — PATCH /api/v1/uploads/{id}),
 * блок «Расчёт печати и цены» (B04 + B05, components/SliceCalc.tsx) — сразу под габаритами,
 * ниже свёрнутое «Дополнительно»: надпись или логотип (B30, components/EmbossPanel.tsx)
 * и раскраска по частям (B31, components/PaintPanel.tsx).
 * Повтор заказа из кабинета (B32): параметры прошлого заказа приходят в адресе
 * (?material=…&qty=…, lib/account.ts: parsePreset) и подставляются в калькулятор.
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import EmbossPanel from "@/components/EmbossPanel";
import PaintPanel from "@/components/PaintPanel";
import SliceCalc from "@/components/SliceCalc";
import { parsePreset, type Preset } from "@/lib/account";
import { apiErrorText, caughtErrorText } from "@/lib/errors";
import {
  formatBytes,
  formatDims,
  UNIT_SCALE,
  type Units,
  type Upload,
  warningText,
} from "@/lib/mesh";

// Three.js работает только в браузере — не рендерим на сервере.
const ModelViewer = dynamic(() => import("@/components/ModelViewer"), {
  ssr: false,
  loading: () => (
    <div
      className="flex h-[420px] items-center justify-center rounded-lg border"
      style={{ borderColor: "var(--ink-muted)" }}
    >
      Загружаем 3D-просмотр…
    </div>
  ),
});

export default function ModelPage() {
  const { id } = useParams<{ id: string }>();
  const [upload, setUpload] = useState<Upload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showUnits, setShowUnits] = useState<Units>("mm"); // в чём показывать габариты
  const [saving, setSaving] = useState(false);
  const [preset, setPreset] = useState<Preset | null>(null); // повтор заказа (B32)

  useEffect(() => {
    setPreset(parsePreset(window.location.search));
    fetch(`/api/v1/uploads/${id}`)
      .then(async (r) => {
        if (!r.ok)
          throw new Error(
            r.status === 404 ? "Модель не найдена: ссылка устарела или файл уже удалён. Загрузите модель заново." : apiErrorText(r.status),
          );
        setUpload((await r.json()) as Upload);
      })
      .catch((e: unknown) => setError(caughtErrorText(e)));
  }, [id]);

  async function setFileUnits(units: Units) {
    if (!upload || upload.units === units) return;
    setSaving(true);
    try {
      const r = await fetch(`/api/v1/uploads/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ units }),
      });
      if (r.ok) setUpload((await r.json()) as Upload);
    } finally {
      setSaving(false);
    }
  }

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-16">
        <p role="alert">{error}</p>
        <Link href="/upload" style={{ color: "var(--filament-text)" }}>
          ← Загрузить другую модель
        </Link>
      </main>
    );
  }
  if (!upload) {
    return <main className="mx-auto max-w-3xl px-4 py-16">Загружаем…</main>;
  }

  const m = upload.mesh;
  const fileUrl = `/api/v1/uploads/${upload.id}/file`;
  // Модель из каталога (B20) или редактора (B21): назад — туда, откуда пришли, единицы
  // известны (мм), материал подставлен.
  const fromCatalog = upload.source === "catalog" && upload.catalog;
  const fromEditor = upload.source === "editor" && upload.editor;
  const fromEmboss = upload.source === "emboss" && upload.emboss;
  const fromPaint = upload.source === "paint" && upload.paint;
  const knownUnits = fromCatalog || fromEditor || fromEmboss || fromPaint;

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-16">
      {fromCatalog ? (
        <Link
          href={`/catalog/${upload.catalog!.slug}`}
          className="text-sm"
          style={{ color: "var(--filament-text)" }}
        >
          ← Назад к модели в каталоге
        </Link>
      ) : fromEditor ? (
        <Link
          href={`/editors/${upload.editor!.slug}`}
          className="text-sm"
          style={{ color: "var(--filament-text)" }}
        >
          ← Назад в редактор
        </Link>
      ) : fromEmboss ? (
        <Link
          href={`/upload/${upload.emboss!.parent_id}`}
          className="text-sm"
          style={{ color: "var(--filament-text)" }}
        >
          ← Назад к модели без тиснения
        </Link>
      ) : fromPaint ? (
        <Link
          href={`/upload/${upload.paint!.parent_id}`}
          className="text-sm"
          style={{ color: "var(--filament-text)" }}
        >
          ← Назад к модели без раскраски
        </Link>
      ) : (
        <Link
          href="/upload"
          className="text-sm"
          style={{ color: "var(--filament-text)" }}
        >
          ← Загрузить другую модель
        </Link>
      )}
      <h1 className="text-2xl font-bold leading-tight">
        {fromCatalog ? upload.catalog!.title : fromEditor ? upload.editor!.title : upload.original_name}
      </h1>
      {fromEditor && upload.editor!.summary && (
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
          Параметры: {upload.editor!.summary}
        </p>
      )}
      {fromEmboss && (
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
          Это копия модели «{upload.emboss!.parent_name}» с тиснением: {upload.emboss!.summary}.
        </p>
      )}
      {fromPaint && (
        <div className="flex flex-col gap-2 text-sm" style={{ color: "var(--ink-muted)" }}>
          <p>
            Это копия модели «{upload.paint!.parent_name}» в цветах: {upload.paint!.summary}.
          </p>
          <ul className="flex flex-wrap gap-3">
            {upload.paint!.colors.map((c) => (
              <li key={c.key} className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="inline-block h-4 w-4 rounded-full border"
                  style={{ background: c.hex, borderColor: "var(--ink-muted)" }}
                />
                {c.name}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ModelViewer
        url={fileUrl}
        ext={upload.ext}
        scale={UNIT_SCALE[upload.units]}
        keepMaterials={Boolean(fromPaint)}
      />

      <section
        className="flex flex-col gap-4 rounded-lg border p-6"
        style={{ borderColor: "var(--ink-muted)" }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">
            Габариты: {formatDims(m.bbox_mm, showUnits)}
          </h2>
          <Toggle
            value={showUnits}
            onChange={setShowUnits}
            labels={{ mm: "мм", inch: "дюймы" }}
            title="Показывать в"
          />
        </div>

        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <dt style={{ color: "var(--ink-muted)" }}>Объём</dt>
          <dd>{m.volume_cm3.toFixed(1).replace(".", ",")} см³</dd>
          <dt style={{ color: "var(--ink-muted)" }}>Треугольников</dt>
          <dd>{m.triangles.toLocaleString("ru-RU")}</dd>
          <dt style={{ color: "var(--ink-muted)" }}>Сетка</dt>
          <dd>{m.watertight ? "замкнута" : "есть дыры"}</dd>
          <dt style={{ color: "var(--ink-muted)" }}>Файл</dt>
          <dd>
            {upload.ext.toUpperCase()}, {formatBytes(upload.size_bytes)}
          </dd>
        </dl>

        {!knownUnits && (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span style={{ color: "var(--ink-muted)" }}>Единицы в файле:</span>
            <Toggle
              value={upload.units}
              onChange={(u) => void setFileUnits(u)}
              labels={{ mm: "мм", inch: "дюймы" }}
              disabled={saving}
            />
            {m.unit_hint === "maybe_inches" && upload.units === "mm" && (
              <span>Модель очень маленькая — возможно, файл в дюймах?</span>
            )}
          </div>
        )}

        {m.warnings.length > 0 && (
          <ul className="flex flex-col gap-1 text-sm">
            {m.warnings.map((w) => (
              <li key={w}>⚠ {warningText(w)}</li>
            ))}
          </ul>
        )}

        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
          Номер загрузки: <code>{upload.id}</code>.
        </p>
      </section>

      {/* key: после смены «мм → дюймы» сервер удаляет старые расчёты печати и цены —
          перерисовываем калькулятор с нуля, чтобы не показывать цену для старых единиц. */}
      <SliceCalc
        key={upload.units}
        uploadId={upload.id}
        defaultMaterial={
          fromCatalog
            ? upload.catalog!.material
            : fromEditor
              ? upload.editor!.material
              : (fromEmboss && upload.emboss!.material) ||
                (fromPaint && upload.paint!.material) ||
                "PLA"
        }
        preset={preset}
      />
      {/* Тиснение и раскраска — дополнительные услуги, свёрнуты под расчётом (фокус-группа:
          новичок пришёл за ценой, длинная форма надписи сверху уводила его со страницы). */}
      <details
        className="rounded-lg border p-4 sm:p-6"
        style={{ borderColor: "var(--ink-muted)" }}
        data-testid="extras"
      >
        <summary className="cursor-pointer text-lg font-semibold">
          Дополнительно: надпись, логотип, раскраска
        </summary>
        <div className="mt-4 flex flex-col gap-6">
          {/* Раскрашенную модель (3MF с цветами) не тисним и не красим заново: тиснение склеило бы
              детали в одну и потеряло цвета. Хотите иначе — вернитесь к исходной модели. */}
          {fromPaint ? (
            <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Изменить цвета или добавить надпись можно на{" "}
              <Link href={`/upload/${upload.paint!.parent_id}`} style={{ color: "var(--filament-text)" }}>
                исходной модели
              </Link>
              .
            </p>
          ) : (
            <>
              <EmbossPanel uploadId={upload.id} logoName={upload.logo?.name ?? null} />
              {/* key: после смены «мм → дюймы» сервер удаляет разборку на детали — начинаем заново. */}
              <PaintPanel key={upload.units} uploadId={upload.id} />
            </>
          )}
        </div>
      </details>
    </main>
  );
}

/** Переключатель из двух кнопок: мм / дюймы. */
function Toggle({
  value,
  onChange,
  labels,
  title,
  disabled,
}: {
  value: Units;
  onChange: (u: Units) => void;
  labels: Record<Units, string>;
  title?: string;
  disabled?: boolean;
}) {
  return (
    <div
      className="inline-flex overflow-hidden rounded-md border text-sm"
      style={{ borderColor: "var(--ink-muted)" }}
      title={title}
    >
      {(["mm", "inch"] as Units[]).map((u) => (
        <button
          key={u}
          type="button"
          disabled={disabled}
          onClick={() => onChange(u)}
          className="px-3 py-1"
          style={
            value === u
              ? { background: "var(--filament)", color: "var(--on-filament)" }
              : { color: "var(--ink)" }
          }
        >
          {labels[u]}
        </button>
      ))}
    </div>
  );
}
