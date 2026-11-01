"use client";

/**
 * Зона загрузки модели (B02, вынесена в компонент в B14).
 * Используется на главной и на странице /upload: клиент перетаскивает STL/3MF →
 * POST /api/v1/uploads → переход на /upload/<id> (3D-просмотр, расчёт, заказ).
 */

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { NETWORK_ERROR, responseErrorText } from "@/lib/errors";
import { reachGoal } from "@/lib/metrika";
import { MAX_UPLOAD_MB, type Upload, validateFile } from "@/lib/mesh";

type State =
  | { kind: "idle" }
  | { kind: "uploading"; name: string }
  | { kind: "error"; message: string };

type Props = {
  idleText?: string;
  /** Текст оранжевой кнопки внутри зоны (главная, B41): одно действие на первом экране. Без неё — только текст. */
  cta?: string;
};

export default function UploadDropzone({ idleText, cta }: Props) {
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
        setState({ kind: "error", message: await responseErrorText(r) });
        return;
      }
      const upload = (await r.json()) as Upload;
      reachGoal("upload");
      router.push(`/upload/${upload.id}`);
    } catch {
      setState({ kind: "error", message: NETWORK_ERROR });
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
        // Без aria-label: доступное имя берётся из видимого текста (WCAG 2.5.3, Lighthouse label-content-name-mismatch).
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
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
        data-testid="dropzone"
        className={`flex cursor-pointer flex-col items-center gap-2 rounded-md border-2 border-dashed text-center ${cta ? "p-6 sm:p-8" : "p-10"}`}
        style={{
          borderColor: dragOver ? "var(--filament-text)" : "var(--steel)",
          background: dragOver ? "color-mix(in srgb, var(--filament) 10%, transparent)" : undefined,
        }}
      >
        {state.kind === "uploading" ? (
          <span>Загружаем и проверяем «{state.name}»…</span>
        ) : (
          <>
            {/* Кнопка — оформление: кликабельна вся зона (role="button" выше), поэтому это span, не <button>. */}
            {cta && <span className="btn btn-primary w-full sm:w-auto">{cta}</span>}
            <span className={cta ? "text-sm" : "font-medium"} style={cta ? { color: "var(--ink-muted)" } : undefined}>
              {idleText ?? "Перетащите файл сюда или нажмите, чтобы выбрать"}
            </span>
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
        <p role="alert" className="rounded-md border px-4 py-3" style={{ borderColor: "var(--danger)", color: "var(--danger)" }}>
          {state.message}
        </p>
      )}
    </div>
  );
}
