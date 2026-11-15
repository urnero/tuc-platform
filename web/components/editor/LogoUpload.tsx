"use client";

/**
 * Загрузка SVG-логотипа в редакторе (B62, docs/EDITOR.md). Файл уходит на сервер
 * (POST /api/v1/uploads/{id}/logo — там его проверяют: без скриптов, ссылок и текста),
 * а его текст кладётся в стор — окно сразу показывает контуры на модели.
 * Один логотип на модель: новый файл заменяет старый у всех логотипов в окне.
 */

import { useRef, useState } from "react";
import { validateLogoFile } from "@/lib/emboss";
import type { EditorStore } from "@/lib/editor/store";
import { useEditor } from "@/lib/editor/store";

type Props = { uploadId: string; store: EditorStore };

export default function LogoUpload({ uploadId, store }: Props) {
  const logo = useEditor(store, (s) => s.logo);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    const bad = validateLogoFile(file.name, file.size);
    if (bad) {
      setError(bad);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const svg = await file.text();
      const body = new FormData();
      body.append("file", file);
      const r = await fetch(`/api/v1/uploads/${uploadId}/logo`, { method: "POST", body });
      if (!r.ok) {
        const err = (await r.json().catch(() => ({}))) as { detail?: string };
        throw new Error(typeof err.detail === "string" ? err.detail : `Ошибка ${r.status}.`);
      }
      const meta = (await r.json()) as { logo?: { name: string } };
      store.dispatch({ type: "logo", logo: { name: meta.logo?.name ?? file.name, svg } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="flex flex-col gap-2 text-sm" data-testid="logo-upload">
      <div className="flex flex-wrap items-center gap-3">
        {logo ? (
          <span className="min-w-0 truncate">
            Логотип: <strong>{logo.name}</strong>
          </span>
        ) : (
          <span style={{ color: "var(--ink-muted)" }}>Логотип ещё не загружен.</span>
        )}
        <label className="cursor-pointer rounded-md border px-3 py-1.5" style={{ borderColor: "var(--line)" }}>
          {busy ? "Загружаем…" : logo ? "Заменить SVG" : "Выбрать SVG"}
          <input
            ref={input}
            type="file"
            accept=".svg,image/svg+xml"
            className="sr-only"
            disabled={busy}
            data-testid="logo-file"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void upload(f);
            }}
          />
        </label>
      </div>
      {error ? (
        <span role="alert" style={{ color: "var(--danger)" }}>
          {error}
        </span>
      ) : (
        <span className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Только SVG до 1 МБ, текст в нём переведите в кривые. PNG/JPG можно перевести в SVG, например, в Inkscape («Контур → Векторизовать растр»).
        </span>
      )}
    </div>
  );
}
