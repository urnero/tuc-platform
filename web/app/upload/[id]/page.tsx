"use client";

/**
 * Страница загруженной модели (B03): 3D-просмотр, габариты, объём, предупреждения,
 * переключатель «файл в мм / в дюймах» (сохраняется на сервере — PATCH /api/v1/uploads/{id}),
 * блок «Надпись или логотип на модели» (B30, components/EmbossPanel.tsx),
 * блок «Расчёт печати и цены» (B04 + B05, components/SliceCalc.tsx).
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import EmbossPanel from "@/components/EmbossPanel";
import SliceCalc from "@/components/SliceCalc";
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
      style={{ borderColor: "var(--muted)" }}
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

  useEffect(() => {
    fetch(`/api/v1/uploads/${id}`)
      .then(async (r) => {
        if (!r.ok)
          throw new Error(
            r.status === 404 ? "Загрузка не найдена." : `Ошибка ${r.status}.`,
          );
        setUpload((await r.json()) as Upload);
      })
      .catch((e: Error) => setError(e.message));
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
        <Link href="/upload" style={{ color: "var(--accent)" }}>
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
  const knownUnits = fromCatalog || fromEditor || fromEmboss;

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-16">
      {fromCatalog ? (
        <Link
          href={`/catalog/${upload.catalog!.slug}`}
          className="text-sm"
          style={{ color: "var(--accent)" }}
        >
          ← Назад к модели в каталоге
        </Link>
      ) : fromEditor ? (
        <Link
          href={`/editors/${upload.editor!.slug}`}
          className="text-sm"
          style={{ color: "var(--accent)" }}
        >
          ← Назад в редактор
        </Link>
      ) : fromEmboss ? (
        <Link
          href={`/upload/${upload.emboss!.parent_id}`}
          className="text-sm"
          style={{ color: "var(--accent)" }}
        >
          ← Назад к модели без тиснения
        </Link>
      ) : (
        <Link
          href="/upload"
          className="text-sm"
          style={{ color: "var(--accent)" }}
        >
          ← Загрузить другую модель
        </Link>
      )}
      <h1 className="text-2xl font-bold leading-tight">
        {fromCatalog ? upload.catalog!.title : fromEditor ? upload.editor!.title : upload.original_name}
      </h1>
      {fromEditor && upload.editor!.summary && (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Параметры: {upload.editor!.summary}
        </p>
      )}
      {fromEmboss && (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Это копия модели «{upload.emboss!.parent_name}» с тиснением: {upload.emboss!.summary}.
        </p>
      )}

      <ModelViewer
        url={fileUrl}
        ext={upload.ext}
        scale={UNIT_SCALE[upload.units]}
      />

      <section
        className="flex flex-col gap-4 rounded-lg border p-6"
        style={{ borderColor: "var(--muted)" }}
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
          <dt style={{ color: "var(--muted)" }}>Объём</dt>
          <dd>{m.volume_cm3.toFixed(1).replace(".", ",")} см³</dd>
          <dt style={{ color: "var(--muted)" }}>Треугольников</dt>
          <dd>{m.triangles.toLocaleString("ru-RU")}</dd>
          <dt style={{ color: "var(--muted)" }}>Сетка</dt>
          <dd>{m.watertight ? "замкнута" : "есть дыры"}</dd>
          <dt style={{ color: "var(--muted)" }}>Файл</dt>
          <dd>
            {upload.ext.toUpperCase()}, {formatBytes(upload.size_bytes)}
          </dd>
        </dl>

        {!knownUnits && (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span style={{ color: "var(--muted)" }}>Единицы в файле:</span>
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

        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Номер загрузки: <code>{upload.id}</code>. Цена — в блоке ниже.
        </p>
      </section>

      <EmbossPanel uploadId={upload.id} logoName={upload.logo?.name ?? null} />

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
              : (fromEmboss && upload.emboss!.material) || "PLA"
        }
      />
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
      style={{ borderColor: "var(--muted)" }}
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
              ? { background: "var(--accent)", color: "var(--bg)" }
              : { color: "var(--fg)" }
          }
        >
          {labels[u]}
        </button>
      ))}
    </div>
  );
}
