"use client";

/**
 * Страница загрузки модели (B02).
 * Клиент выбирает STL/3MF → отправляем на POST /api/v1/uploads → переходим на страницу
 * модели /upload/<id> (3D-просмотр, габариты, единицы). Цена — в B05.
 */

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { MAX_UPLOAD_MB, type Upload, validateFile } from "@/lib/mesh";

type State =
  | { kind: "idle" }
  | { kind: "uploading"; name: string }
  | { kind: "error"; message: string };

export default function UploadPage() {
  const router = useRouter();
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
      const upload = (await r.json()) as Upload;
      router.push(`/upload/${upload.id}`);
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

    </main>
  );
}
