"use client";

/**
 * «Применить» в редакторе: отправить все наложения на сервер и дождаться сборки.
 * Общий код для кнопки «Применить» в панели (TextToolPanel) и «✓ Готово» в панели
 * инструментов — раньше «Готово» уходило к модели без применения, и надпись терялась
 * (QA 2026-11-08). Хук useApply создаётся один раз на странице редактора и передаётся в панель.
 *
 * Запрос: POST /api/v1/uploads/{id}/embosses (тело — toEmbossBody), опрос
 * GET …/embosses/{job_id} каждые 1,5 с, пока статус queued/running; done → onDone(result_upload_id).
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { EmbossJob } from "../emboss";
import { type EditorStore, overlaysProblem, toEmbossBody } from "./store";

export const POLL_MS = 1500;

type Fetch = typeof fetch;

/** Итог отправки: задание сборки или текст ошибки для клиента. */
export type StartResult = { job: EmbossJob } | { error: string };

/** Отправить наложения на сборку. Проверку (пустой текст, нет SVG…) делает до запроса. */
export async function startApply(uploadId: string, store: EditorStore, fetchFn: Fetch = fetch): Promise<StartResult> {
  const { overlays, logo } = store.getState();
  const problem = overlaysProblem(overlays, logo !== null);
  const body = toEmbossBody(overlays);
  if (problem || !body) return { error: problem ?? "Поставьте надпись или логотип на модель." };
  try {
    const r = await fetchFn(`/api/v1/uploads/${uploadId}/embosses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const res = (await r.json().catch(() => ({}))) as { detail?: { errors?: Record<string, string> } | string };
    if (r.status === 422 && typeof res.detail === "object" && res.detail?.errors) {
      return { error: Object.values(res.detail.errors).join(" ") };
    }
    if (!r.ok) return { error: typeof res.detail === "string" ? res.detail : `Ошибка ${r.status}.` };
    return { job: res as EmbossJob };
  } catch (e) {
    return { error: (e as Error).message || "Нет связи с сервером." };
  }
}

/** Один шаг опроса: свежее задание или null (сервер не ответил — попробуем в следующий раз). */
export async function pollJob(uploadId: string, jobId: string, fetchFn: Fetch = fetch): Promise<EmbossJob | null> {
  try {
    const r = await fetchFn(`/api/v1/uploads/${uploadId}/embosses/${jobId}`);
    return r.ok ? ((await r.json()) as EmbossJob) : null;
  } catch {
    return null;
  }
}

/** Задание ещё собирается. */
export function isWorking(job: EmbossJob | null): boolean {
  return job !== null && (job.status === "queued" || job.status === "running");
}

export type ApplyState = {
  job: EmbossJob | null;
  busy: boolean;
  error: string | null;
  /** Идёт отправка или сборка — кнопки «Применить» и «Готово» показывают «Наносим…». */
  working: boolean;
  apply: () => Promise<void>;
  /** Клиент поменял наложение — прошлый статус и ошибка больше не про него. */
  reset: () => void;
};

/** Хук «Применить»: отправка, опрос, переход на страницу результата. */
export function useApply(uploadId: string, store: EditorStore): ApplyState {
  const router = useRouter();
  const [job, setJob] = useState<EmbossJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!job) return;
    if (job.status === "done" && job.result_upload_id) {
      router.push(`/upload/${job.result_upload_id}`);
      return;
    }
    if (!isWorking(job)) return;
    const timer = setTimeout(async () => {
      const next = await pollJob(uploadId, job.id);
      if (next) setJob(next);
      else setJob({ ...job }); // сервер не ответил — новый круг опроса
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [job, uploadId, router]);

  const apply = useCallback(async () => {
    setBusy(true);
    setError(null);
    const res = await startApply(uploadId, store);
    setBusy(false);
    if ("error" in res) setError(res.error);
    else setJob(res.job);
  }, [uploadId, store]);

  const reset = useCallback(() => {
    setJob(null);
    setError(null);
  }, []);

  return { job, busy, error, working: busy || isWorking(job), apply, reset };
}
