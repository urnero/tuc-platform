"use client";

/**
 * Страница загрузки модели (B02).
 * Клиент выбирает STL/3MF → отправляем на POST /api/v1/uploads → показываем габариты,
 * объём и предупреждения. 3D-просмотр появится в B03, цена — в B05.
 */

import { useRef, useState } from "react";
import {
  formatBytes,
  formatDims,
  MAX_UPLOAD_MB,
  type Upload,
  validateFile,
  warningText,
} from "@/lib/mesh";

type State =
  | { kind: "idle" }
  | { kind: "uploading"; name: string }
  | { kind: "done"; upload: Upload }
  | { kind: "error"; message: string };

export default function UploadPage() {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function send(file: File) {
    const err = validateFile(file.name, file.size);
    if (err) {
      setState({ kind: "error", message: err });
      return;
    }
    setState({ kind: "uploading", name: file.name });
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await fetch("/api/v1/uploads", { method: "POST", body: form });
      if (!r.ok) {
        const detail = (await r.json().catch(() => null))?.detail;
        setState({ kind: "error", message: detail ?? `Ошибка сервера (${r.status}).` });
        return;
      }
      setState({ kind: "done", upload: (await r.json()) as Upload });
    } catch {
      setState({ kind: "error", message: "Не удалось связаться с сервером. Попробуйте ещё раз." });
    }
  }

  function onFiles(files: FileList | null) {
    const file = files?.[0];
    if (file) void send(file);
  }

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-16">
      <p className="text-xs uppercase tracking-widest" style={{ color: "var(--accent)" }}>
        ТУЦ · загрузка модели
      </p>
      <h1 className="text-3xl font-bold leading-tight">Загрузите модель для печати</h1>
      <p className="max-w-prose" style={{ color: "var(--muted)" }}>
        STL или 3MF, до {MAX_UPLOAD_MB} МБ. Мы проверим сетку и покажем габариты.
      </p>

      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onFiles(e.dataTransfer.files);
        }}
        className="cursor-pointer rounded-lg border-2 border-dashed p-10 text-center"
        style={{ borderColor: dragOver ? "var(--accent)" : "var(--muted)" }}
      >
        {state.kind === "uploading" ? (
          <span>Загружаем и проверяем «{state.name}»…</span>
        ) : (
          <span>Перетащите файл сюда или нажмите, чтобы выбрать</span>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".stl,.3mf"
          className="hidden"
          onChange={(e) => onFiles(e.target.files)}
        />
      </div>

      {state.kind === "error" && (
        <p role="alert" className="rounded-md border px-4 py-3" style={{ borderColor: "#c0392b" }}>
          {state.message}
        </p>
      )}

      {state.kind === "done" && <Result upload={state.upload} />}
    </main>
  );
}

function Result({ upload }: { upload: Upload }) {
  const m = upload.mesh;
  return (
    <section className="flex flex-col gap-4 rounded-lg border p-6" style={{ borderColor: "var(--muted)" }}>
      <h2 className="text-xl font-semibold">{upload.original_name}</h2>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        <dt style={{ color: "var(--muted)" }}>Габариты</dt>
        <dd>{formatDims(m.bbox_mm)}</dd>
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
      {m.warnings.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {m.warnings.map((w) => (
            <li key={w}>⚠ {warningText(w)}</li>
          ))}
        </ul>
      )}
      <p className="text-sm" style={{ color: "var(--muted)" }}>
        Номер загрузки: <code>{upload.id}</code>. Расчёт цены появится на следующем шаге.
      </p>
    </section>
  );
}
