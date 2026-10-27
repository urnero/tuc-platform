"use client";

/**
 * Зона загрузки модели (B02, вынесена в компонент в B14).
 * Используется на главной и на странице /upload: клиент перетаскивает STL/3MF →
 * POST /api/v1/uploads → переход на /upload/<id> (3D-просмотр, расчёт, заказ).
 */

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { reachGoal } from "@/lib/metrika";
import { MAX_UPLOAD_MB, type Upload, validateFile } from "@/lib/mesh";

type State =
  | { kind: "idle" }
  | { kind: "uploading"; name: string }
  | { kind: "error"; message: string };

export default function UploadDropzone({ idleText }: { idleText?: string }) {
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
      reachGoal("upload");
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
    <div className="flex flex-col gap-3">
      <div
        role="button"
        tabIndex={0}
        aria-label="Загрузить файл модели"
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
        className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed p-10 text-center"
        style={{ borderColor: dragOver ? "var(--filament-text)" : "var(--ink-muted)" }}
      >
        {state.kind === "uploading" ? (
          <span>Загружаем и проверяем «{state.name}»…</span>
        ) : (
          <>
            <span className="font-medium">{idleText ?? "Перетащите файл сюда или нажмите, чтобы выбрать"}</span>
            <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
              STL или 3MF, до {MAX_UPLOAD_MB} МБ
            </span>
          </>
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
    </div>
  );
}
