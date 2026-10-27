/**
 * Главная (B14): лендинг с зоной загрузки, шагами, преимуществами, материалами и примерами работ.
 * Тексты — web/lib/landing.ts и web/lib/works.ts; цены — из API (/api/v1/pricing),
 * обновляются раз в 10 минут (ISR), без API страница рендерится без цен.
 */

import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import UploadDropzone from "@/components/UploadDropzone";
import { BENEFITS, loadPricing, materialCards, minOrderText, STEPS } from "@/lib/landing";
import { WORKS, workImageUrl, worksTitle } from "@/lib/works";

// Заголовок и описание — в app/layout.tsx; здесь только канонический адрес главной (B25).
export const metadata: Metadata = { alternates: { canonical: "/" } };

/** Заглушка вместо фото работы: контур куба в цвете акцента. */
function CubePlaceholder() {
  return (
    <svg viewBox="0 0 120 120" className="h-16 w-16" aria-hidden="true" fill="none" stroke="var(--accent)" strokeWidth="3">
      <path d="M60 14 104 36v48L60 106 16 84V36z" />
      <path d="M16 36l44 22 44-22M60 58v48" />
    </svg>
  );
}

function SectionTitle({ id, title, subtitle }: { id?: string; title: string; subtitle?: string }) {
  return (
    <div id={id} className="flex scroll-mt-24 flex-col gap-1">
      <h2 className="text-2xl font-bold">{title}</h2>
      {subtitle && (
        <p className="max-w-prose" style={{ color: "var(--muted)" }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}

export default async function Home() {
  const pricing = await loadPricing();
  const materials = materialCards(pricing);
  const minOrder = minOrderText(pricing);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-20 px-4 pb-20 pt-10">
      {/* Герой: заголовок + загрузка прямо с главной */}
      <section className="grid items-center gap-8 md:grid-cols-2">
        <div className="flex flex-col gap-5">
          <h1 className="text-4xl font-bold leading-tight">Загрузите модель — получите цену за минуту</h1>
          <p className="max-w-prose text-lg" style={{ color: "var(--muted)" }}>
            FDM-печать из PLA, PETG и ABS по вашим STL/3MF. Цену считает сервер, оплата картой онлайн, статус заказа
            — по ссылке.{minOrder && <> {minOrder}.</>}
          </p>
          <div className="flex flex-wrap gap-4 text-sm">
            <a href="#how" className="underline-offset-2 hover:underline" style={{ color: "var(--accent)" }}>
              Как это работает ↓
            </a>
            <Link href="/catalog" className="underline-offset-2 hover:underline" style={{ color: "var(--accent)" }}>
              Нет модели? Выберите в каталоге →
            </Link>
            <Link href="/editors" className="underline-offset-2 hover:underline" style={{ color: "var(--accent)" }}>
              Или задайте размеры в редакторе →
            </Link>
          </div>
        </div>
        <UploadDropzone idleText="Перетащите STL или 3MF сюда" />
      </section>

      {/* Как это работает */}
      <section className="flex flex-col gap-6">
        <SectionTitle id="how" title="Как это работает" subtitle="Четыре шага от файла до готовой детали — без менеджера." />
        <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex flex-col gap-2 rounded-lg border p-5" style={{ borderColor: "color-mix(in srgb, var(--muted) 35%, transparent)" }}>
              <span className="text-sm font-semibold" style={{ color: "var(--accent)" }}>
                Шаг {i + 1}
              </span>
              <h3 className="font-semibold">{s.title}</h3>
              <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
                {s.text}
              </p>
            </li>
          ))}
        </ol>
      </section>

      {/* Преимущества */}
      <section className="flex flex-col gap-6">
        <SectionTitle title="Почему удобно" />
        <ul className="grid gap-x-8 gap-y-6 sm:grid-cols-2">
          {BENEFITS.map((b) => (
            <li key={b.title} className="flex flex-col gap-1">
              <h3 className="font-semibold">{b.title}</h3>
              <p className="max-w-prose leading-relaxed" style={{ color: "var(--muted)" }}>
                {b.text}
              </p>
            </li>
          ))}
        </ul>
      </section>

      {/* Материалы и цены из прайса */}
      <section className="flex flex-col gap-6">
        <SectionTitle
          id="materials"
          title="Материалы"
          subtitle="Цена складывается из граммов пластика и часов печати — точную сумму покажет расчёт после загрузки."
        />
        <ul className="grid gap-4 sm:grid-cols-3">
          {materials.map((m) => (
            <li key={m.name} className="flex flex-col gap-2 rounded-lg border p-5" style={{ borderColor: "color-mix(in srgb, var(--muted) 35%, transparent)" }}>
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="text-lg font-semibold">{m.name}</h3>
                {m.price && (
                  <span className="text-sm font-medium" style={{ color: "var(--accent)" }}>
                    {m.price}
                  </span>
                )}
              </div>
              {m.tagline && <p className="text-sm font-medium">{m.tagline}</p>}
              <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
                {m.text}
              </p>
            </li>
          ))}
        </ul>
      </section>

      {/* Примеры работ / что печатаем */}
      <section className="flex flex-col gap-6">
        <SectionTitle id="works" title={worksTitle(WORKS)} subtitle="Нет своей модели? Посмотрите готовые в каталоге или напишите нам — подскажем, как подготовить файл." />
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {WORKS.map((w) => {
            const src = workImageUrl(w);
            return (
              <li key={w.title} className="flex flex-col overflow-hidden rounded-lg border" style={{ borderColor: "color-mix(in srgb, var(--muted) 35%, transparent)" }}>
                <div className="relative flex aspect-[4/3] items-center justify-center" style={{ background: "color-mix(in srgb, var(--muted) 12%, transparent)" }}>
                  {src ? (
                    <Image src={src} alt={w.title} fill unoptimized sizes="(min-width: 1024px) 320px, (min-width: 640px) 50vw, 100vw" className="object-cover" />
                  ) : (
                    <CubePlaceholder />
                  )}
                </div>
                <div className="flex flex-col gap-1 p-4">
                  <div className="flex items-baseline justify-between gap-2">
                    <h3 className="font-semibold">{w.title}</h3>
                    <span className="text-xs uppercase tracking-wider" style={{ color: "var(--accent)" }}>
                      {w.material}
                    </span>
                  </div>
                  <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
                    {w.text}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Призыв внизу */}
      <section className="flex flex-col items-start gap-4 rounded-lg p-8" style={{ background: "color-mix(in srgb, var(--accent) 12%, transparent)" }}>
        <h2 className="text-2xl font-bold">Готовы? Загрузите модель</h2>
        <p className="max-w-prose" style={{ color: "var(--muted)" }}>
          Расчёт ни к чему не обязывает: цена видна до оформления заказа.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link href="/upload" className="rounded-md px-4 py-2 text-sm font-medium" style={{ background: "var(--accent)", color: "var(--bg, #fff)" }}>
            Загрузить модель
          </Link>
          <Link href="/about" className="rounded-md border px-4 py-2 text-sm" style={{ borderColor: "var(--accent)", color: "var(--accent)" }}>
            О студии
          </Link>
        </div>
      </section>
    </main>
  );
}
