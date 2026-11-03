"use client";

/**
 * Интерактивный редактор модели (B60, docs/EDITOR.md): /upload/[id]/edit.
 * Окно 3D-просмотра на весь экран, панель инструментов сбоку (десктоп) или снизу (телефон):
 * «Текст» — надпись ставится мышью/пальцем на поверхность (components/editor/EditorCanvas.tsx,
 * панель — TextToolPanel.tsx); «Логотип» — то же для SVG-логотипа (B62, загрузка —
 * editor/LogoUpload.tsx, SVG уже загруженного логотипа берём из GET …/logo); «Цвет» — раскраска по частям (B63,
 * components/PaintPanel.tsx как есть); «Готово» — назад на страницу модели.
 * Состояние редактора — одно хранилище lib/editor/store.ts, создаётся на страницу.
 * ?overlay=<job_id> (B60c, «Изменить в редакторе» на странице результата): прошлая надпись или логотип
 * читается из GET /api/v1/uploads/{id}/embosses/{job_id} и снова стоит на модели, выбранная.
 * ?tool=logo|text|color (B62a): сразу открыть инструмент — так ведёт кнопка «Логотип в редакторе».
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import TextToolPanel from "@/components/editor/TextToolPanel";
import PaintPanel from "@/components/PaintPanel";
import { gizmoHint } from "@/lib/editor/phone";
import { createEditorStore, overlaysFromParams, type Tool, toolFromParam, useEditor } from "@/lib/editor/store";
import { apiErrorText, caughtErrorText } from "@/lib/errors";
import { UNIT_SCALE, type Upload } from "@/lib/mesh";

const EditorCanvas = dynamic(() => import("@/components/editor/EditorCanvas"), {
  ssr: false,
  loading: () => <div className="flex h-full items-center justify-center text-sm">Загружаем 3D-редактор…</div>,
});

const TOOLS: { value: Tool; label: string; icon: string }[] = [
  { value: "text", label: "Текст", icon: "T" },
  { value: "logo", label: "Логотип", icon: "◆" },
  { value: "color", label: "Цвет", icon: "●" },
  { value: "done", label: "Готово", icon: "✓" },
];

export default function EditorPage() {
  const { id } = useParams<{ id: string }>();
  const store = useMemo(() => createEditorStore(), []);
  const tool = useEditor(store, (s) => s.tool);
  const hasSelection = useEditor(store, (s) => s.selectedId !== null);
  const gizmo = useEditor(store, (s) => s.gizmo);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restoreNote, setRestoreNote] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/v1/uploads/${id}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "Модель не найдена: ссылка устарела или файл уже удалён." : apiErrorText(r.status));
        setUpload((await r.json()) as Upload);
      })
      .catch((e: unknown) => setError(caughtErrorText(e)));
  }, [id]);

  // У модели уже есть логотип (загружали раньше или старой формой) — берём его SVG,
  // чтобы окно сразу показало контуры (B62). Не получилось — клиент загрузит заново.
  const logoName = upload?.logo?.name;
  useEffect(() => {
    if (!logoName) return;
    const ctrl = new AbortController();
    fetch(`/api/v1/uploads/${id}/logo`, { signal: ctrl.signal })
      .then(async (r) => {
        if (r.ok) store.dispatch({ type: "logo", logo: { name: logoName, svg: await r.text() } });
      })
      .catch(() => {});
    return () => ctrl.abort();
  }, [id, logoName, store]);

  // ?tool=logo — со страницы модели «Логотип в редакторе» (B62a): сразу нужный инструмент.
  useEffect(() => {
    const tool = toolFromParam(new URLSearchParams(window.location.search).get("tool"));
    if (tool) store.dispatch({ type: "tool", tool });
  }, [store]);

  // Вернулись с результата: кладём прошлую надпись в стор (B60c). Ошибка — не беда:
  // редактор работает как обычно, клиент просто ставит надпись заново.
  useEffect(() => {
    const jobId = new URLSearchParams(window.location.search).get("overlay");
    if (!jobId) return;
    const ctrl = new AbortController();
    fetch(`/api/v1/uploads/${id}/embosses/${encodeURIComponent(jobId)}`, { signal: ctrl.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error("job");
        const job = (await r.json()) as { params?: Record<string, unknown> };
        // B65: в сборке могло быть несколько наложений — возвращаем все, по порядку.
        const overlays = overlaysFromParams(jobId, job.params);
        if (overlays.length === 0) throw new Error("params");
        overlays.forEach((overlay) => store.dispatch({ type: "restore", overlay }));
      })
      .catch((e: unknown) => {
        if ((e as Error)?.name === "AbortError") return;
        setRestoreNote("Прошлое наложение открыть не удалось — поставьте его заново.");
      });
    return () => ctrl.abort();
  }, [id, store]);

  // Esc снимает выбор, Delete убирает выбранную надпись, Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y) —
  // отменить / повторить (B65; на Mac — Cmd).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      const s = store.getState();
      const key = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && (key === "z" || key === "y" || key === "я" || key === "н")) {
        e.preventDefault();
        const redo = key === "y" || key === "н" || e.shiftKey;
        store.dispatch({ type: redo ? "redo" : "undo" });
        return;
      }
      if (e.key === "Escape") store.dispatch({ type: "select", id: null });
      if ((e.key === "Delete" || e.key === "Backspace") && s.selectedId) store.dispatch({ type: "remove", id: s.selectedId });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [store]);

  const backHref = `/upload/${id}`;

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-16">
        <p role="alert" style={{ color: "var(--danger)" }}>
          {error}
        </p>
        <Link href="/upload" className="underline">
          Загрузить модель
        </Link>
      </main>
    );
  }

  return (
    <main
      className="fixed inset-0 z-50 flex flex-col md:flex-row"
      style={{ background: "var(--surface)", color: "var(--ink)" }}
      data-testid="editor"
    >
      {/* Панель инструментов: слева на десктопе, снизу на телефоне. */}
      <nav
        className="order-2 flex shrink-0 justify-around border-t md:order-1 md:w-20 md:flex-col md:justify-start md:gap-1 md:border-r md:border-t-0 md:py-3"
        style={{ borderColor: "var(--line)", background: "var(--surface-raised)" }}
        aria-label="Инструменты"
      >
        {TOOLS.map((t) =>
          t.value === "done" ? (
            <Link key={t.value} href={backHref} className="flex flex-1 flex-col items-center gap-1 px-2 py-2 text-xs md:flex-none" data-testid="tool-done">
              <span className="text-lg leading-none" aria-hidden>
                {t.icon}
              </span>
              {t.label}
            </Link>
          ) : (
            <button
              key={t.value}
              type="button"
              className="flex flex-1 flex-col items-center gap-1 rounded-lg px-2 py-2 text-xs md:flex-none"
              style={tool === t.value ? { background: "var(--filament)", color: "#fff" } : undefined}
              aria-pressed={tool === t.value}
              onClick={() => store.dispatch({ type: "tool", tool: t.value })}
              data-testid={`tool-${t.value}`}
            >
              <span className="text-lg leading-none" aria-hidden>
                {t.icon}
              </span>
              {t.label}
            </button>
          ),
        )}
      </nav>

      {/* Окно просмотра (или раскраска во всю ширину для инструмента «Цвет»). */}
      <section className="order-1 relative min-h-0 flex-1 md:order-2" aria-label="Окно 3D-просмотра">
        <header
          className="pointer-events-none absolute left-0 right-0 top-0 z-10 flex items-center justify-between gap-2 px-3 py-2 text-sm"
          style={{ color: "#f3efe7", textShadow: "0 1px 2px rgba(0,0,0,.6)" }}
        >
          <span className="truncate font-semibold">{upload?.original_name ?? "Редактор"}</span>
          <Link href={backHref} className="pointer-events-auto underline">
            ← К модели
          </Link>
        </header>
        {!upload ? (
          <div className="flex h-full items-center justify-center text-sm">Загружаем…</div>
        ) : tool === "color" ? (
          <div className="h-full overflow-auto px-4 pb-6 pt-12">
            <PaintPanel key={upload.units} uploadId={upload.id} />
          </div>
        ) : (
          <div className="h-full">
            <EditorCanvas url={`/api/v1/uploads/${upload.id}/file`} ext={upload.ext} scale={UNIT_SCALE[upload.units]} store={store} />
          </div>
        )}
        {/* Подсказка на телефоне (B60b): наведения пальцем нет, поэтому говорим, что делать. */}
        {upload && (tool === "text" || tool === "logo") && (
          <p
            className="pointer-events-none absolute bottom-2 left-2 right-2 z-10 rounded-lg px-3 py-1.5 text-center text-xs md:hidden"
            style={{ background: "rgba(0,0,0,.55)", color: "#f3efe7" }}
            data-testid="editor-phone-hint"
          >
            {hasSelection ? gizmoHint(gizmo, tool === "logo" ? "logo" : "text") : tool === "logo" ? "Коснитесь модели, чтобы поставить логотип" : "Коснитесь модели, чтобы поставить надпись"}
          </p>
        )}
      </section>

      {/* Панель параметров выбранного инструмента: справа на десктопе, над инструментами на телефоне. */}
      {tool !== "color" && upload && (
        <aside
          className="order-1 max-h-[45vh] shrink-0 overflow-auto border-t px-4 py-3 md:order-3 md:max-h-none md:w-80 md:border-l md:border-t-0"
          style={{ borderColor: "var(--line)", background: "var(--surface-raised)" }}
          aria-label="Параметры инструмента"
        >
          {restoreNote && (tool === "text" || tool === "logo") && (
            <p className="mb-2 text-sm" role="status" style={{ color: "var(--ink-muted)" }} data-testid="restore-note">
              {restoreNote}
            </p>
          )}
          {(tool === "text" || tool === "logo") && <TextToolPanel key={tool} uploadId={upload.id} store={store} />}
        </aside>
      )}
    </main>
  );
}
