"use client";

/**
 * Кнопка «Заказать» в каталоге (B20): POST /api/v1/catalog/<slug>/upload делает из модели
 * каталога обычную загрузку, и клиент попадает на /upload/<id> — расчёт печати, цена, заказ.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Upload } from "@/lib/mesh";
import { buttonClass } from "@/lib/ui";

type Props = {
  slug: string;
  /** Крупная кнопка на странице модели или маленькая в карточке. */
  size?: "lg" | "sm";
};

export default function CatalogOrderButton({ slug, size = "sm" }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function order() {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/v1/catalog/${slug}/upload`, { method: "POST" });
      if (!r.ok) {
        const detail = (await r.json().catch(() => null))?.detail;
        setError(detail ?? `Ошибка сервера (${r.status}).`);
        return;
      }
      const upload = (await r.json()) as Upload;
      router.push(`/upload/${upload.id}`);
    } catch {
      setError("Не удалось связаться с сервером. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={() => void order()}
        disabled={busy}
        className={buttonClass("primary", size === "lg" ? "md" : "sm", "w-fit")}
      >
        {busy ? "Готовим…" : "Заказать"}
      </button>
      {error && (
        <p role="alert" className="text-sm" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
    </div>
  );
}
