/**
 * Главная как воронка (B41, была лендингом B14). Порядок блоков — сверху вниз по пути клиента:
 * первый экран с одним действием (загрузить) → доверие (мастерская, факты о парке, работы) →
 * как это работает → материалы с ценой «от» → вопросы-ответы → контакты и карта → призыв внизу.
 *
 * Тексты — web/lib/landing.ts (STUDIO, FACTS, FAQ, STEPS) и web/lib/works.ts; контакты — web/lib/company.ts;
 * цены — из API (/api/v1/pricing) раз в 10 минут (ISR), без API страница рендерится без цен.
 * На главной нет Three.js и других тяжёлых скриптов — только зона загрузки (ради Lighthouse mobile ≥ 90).
 */

import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import UploadDropzone from "@/components/UploadDropzone";
import { Button } from "@/components/ui";
import { COMPANY, contactRows, mapEmbedUrl } from "@/lib/company";
import { FACTS, FAQ, faqJsonLd, loadMaterials, loadPricing, materialCards, minOrderText, STEPS, STUDIO } from "@/lib/landing";
import { WORKS, workImageUrl, worksTitle } from "@/lib/works";

// Заголовок и описание — в app/layout.tsx; здесь только канонический адрес главной (B25).
export const metadata: Metadata = { alternates: { canonical: "/" } };

/** Заглушка вместо фото работы: контур знака BroPrint на песке (docs/DESIGN.md → «Фото»). */
function MarkPlaceholder() {
  return (
    <svg viewBox="0 0 120 120" className="h-14 w-14" aria-hidden="true" fill="none" stroke="var(--steel)" strokeWidth="3">
      <path d="M26,14H69.0A21.0,21.0 0 0 1 69.0,56H26Q22,56 22,52V18Q22,14 26,14ZM47,30.0H63A5,5 0 0 1 63,40.0H47A5,5 0 0 1 47,30.0Z" />
      <path d="M26,62H76.0A22.0,22.0 0 0 1 76.0,106H26Q22,106 22,102V66Q22,62 26,62ZM47,79.0H69A5,5 0 0 1 69,89.0H47A5,5 0 0 1 47,79.0Z" />
    </svg>
  );
}

function SectionTitle({ id, title, subtitle }: { id?: string; title: string; subtitle?: string }) {
  return (
    <div id={id} className="flex scroll-mt-24 flex-col gap-2">
      <h2>{title}</h2>
      {subtitle && (
        <p className="t-lead max-w-prose" style={{ color: "var(--ink-muted)" }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}

export default async function Home() {
  const [pricing, materialItems] = await Promise.all([loadPricing(), loadMaterials()]);
  const materials = materialCards(pricing, materialItems);
  const minOrder = minOrderText(pricing);
  const map = mapEmbedUrl(COMPANY.pickupMapUrl);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-16 px-4 pb-20 pt-6 md:gap-24 md:pt-12">
      {/* 1. Первый экран: заголовок, одна фраза, зона загрузки с оранжевой кнопкой. На телефоне всё влезает без прокрутки. */}
      <section className="grid items-center gap-6 md:grid-cols-[1.1fr_1fr] md:gap-10" aria-labelledby="hero-title">
        <div className="flex flex-col gap-4 md:gap-6">
          {/* Заголовок — не длиннее двух строк на телефоне (docs/DESIGN.md, display). */}
          <h1 id="hero-title">Напечатаем вашу модель</h1>
          <p className="t-lead max-w-prose" style={{ color: "var(--ink-muted)" }}>
            Цена — за минуту: загрузите STL или 3MF, сервер посчитает печать и покажет сумму до заказа. Оплата картой
            или по счёту, статус заказа по ссылке.{minOrder && <> {minOrder}.</>}
          </p>
          <ul className="t-caption flex flex-wrap gap-x-5 gap-y-2" style={{ color: "var(--ink-muted)" }} aria-label="Коротко о мастерской">
            <li>Москва · своя мастерская</li>
            <li>PLA, PETG, нейлон, карбон, смолы</li>
            <li>до 256 мм</li>
            <li>самовывоз или курьер</li>
          </ul>
        </div>
        <div className="card flex flex-col gap-3 overflow-hidden p-0">
          {/* Паттерн «Слои» — только декоративная полоса над зоной, текста на нём нет (брендбук). */}
          <div className="layers layers-band h-10 md:h-14" aria-hidden="true" />
          <div className="flex flex-col gap-3 p-4 md:p-6">
            <UploadDropzone cta="Загрузить модель" idleText="или перетащите файл сюда" />
            <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
              Нет файла?{" "}
              <Link href="/catalog" className="underline underline-offset-2" style={{ color: "var(--filament-text)" }}>
                Выберите в каталоге
              </Link>{" "}
              или{" "}
              <Link href="/editors" className="underline underline-offset-2" style={{ color: "var(--filament-text)" }}>
                задайте размеры в редакторе
              </Link>
              .
            </p>
          </div>
        </div>
      </section>

      {/* 2. Доверие: рассказ, факты о парке, срок */}
      <section className="flex flex-col gap-8" aria-labelledby="studio-title">
        <div className="grid gap-8 md:grid-cols-[1fr_1.2fr] md:gap-12">
          <div className="flex flex-col gap-4">
            <h2 id="studio-title">{STUDIO.title}</h2>
            <p className="max-w-prose leading-relaxed">{STUDIO.text}</p>
            <p className="max-w-prose leading-relaxed" style={{ color: "var(--ink-muted)" }}>
              {STUDIO.leadTime}
            </p>
            <Link href="/about" className="text-sm underline underline-offset-2" style={{ color: "var(--filament-text)" }}>
              Подробнее о мастерской →
            </Link>
          </div>
          <dl className="grid grid-cols-2 gap-3 md:gap-4">
            {FACTS.map((f) => (
              <div key={f.label} className="card flex flex-col gap-1">
                <dt className="sr-only">{f.label}</dt>
                <dd className="t-heading" style={{ color: "var(--filament-text)" }}>
                  {f.value}
                </dd>
                <dd className="text-sm leading-snug" style={{ color: "var(--ink-muted)" }}>
                  {f.label}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        {/* Примеры работ / что печатаем — на песке, пока фото нет — контур знака */}
        <div className="flex flex-col gap-5">
          <SectionTitle id="works" title={worksTitle(WORKS)} />
          <ul className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-3">
            {WORKS.map((w) => {
              const src = workImageUrl(w);
              return (
                <li key={w.title} className="card-sand flex flex-col overflow-hidden p-0">
                  <div className="relative flex aspect-[4/3] items-center justify-center">
                    {src ? (
                      <Image src={src} alt={w.title} fill unoptimized sizes="(min-width: 1024px) 360px, (min-width: 640px) 50vw, 100vw" className="object-cover" />
                    ) : (
                      <MarkPlaceholder />
                    )}
                  </div>
                  <div className="flex flex-col gap-1 p-3 md:p-4" style={{ background: "var(--surface-raised)" }}>
                    <div className="flex flex-col items-baseline justify-between gap-1 sm:flex-row sm:gap-2">
                      <h3 className="text-base leading-snug">{w.title}</h3>
                      <span className="t-caption shrink-0" style={{ color: "var(--filament-text)" }}>
                        {w.material}
                      </span>
                    </div>
                    <p className="text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                      {w.text}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </section>

      {/* 3. Как это работает */}
      <section className="flex flex-col gap-6" aria-labelledby="how">
        <SectionTitle id="how" title="Как это работает" subtitle="Четыре шага от файла до готовой детали — без переписки с менеджером." />
        <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="card flex flex-col gap-2">
              <span className="t-caption" style={{ color: "var(--filament-text)" }}>
                Шаг {i + 1}
              </span>
              <h3 className="text-base leading-snug">{s.title}</h3>
              <p className="text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                {s.text}
              </p>
            </li>
          ))}
        </ol>
      </section>

      {/* 4. Материалы и цены «от» из прайса */}
      <section className="flex flex-col gap-6" aria-labelledby="materials">
        <SectionTitle
          id="materials"
          title="Материалы и цены"
          subtitle="Цена складывается из граммов пластика и часов печати — точную сумму покажет расчёт после загрузки."
        />
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {materials.map((m) => (
            <li key={m.name} className="card flex flex-col gap-2">
              <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
                <h3>{m.name}</h3>
                {m.price && (
                  <span
                    className="t-caption"
                    style={{ color: m.onRequest ? "var(--ink-muted)" : "var(--filament-text)" }}
                  >
                    {m.price}
                  </span>
                )}
              </div>
              {m.tagline && <p className="text-sm font-medium">{m.tagline}</p>}
              <p className="text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                {m.text}
              </p>
            </li>
          ))}
        </ul>
        <p className="max-w-prose text-sm" style={{ color: "var(--ink-muted)" }}>
          Смолу и материалы не из списка считаем вручную: выберите смолу на странице расчёта и оставьте заявку — или
          напишите в{" "}
          <Link href="/contacts" className="underline underline-offset-2" style={{ color: "var(--filament-text)" }}>
            контакты
          </Link>
          .
        </p>
      </section>

      {/* 5. Вопросы и ответы — нативные <details>, без скриптов; разметка FAQPage для поиска */}
      <section className="flex flex-col gap-6" aria-labelledby="faq">
        <SectionTitle id="faq" title="Вопросы и ответы" />
        <div className="card flex flex-col p-0">
          {FAQ.map((f) => (
            <details key={f.q} className="faq-item group">
              <summary className="flex cursor-pointer items-center justify-between gap-4 px-4 py-4 font-semibold md:px-6">
                <span>{f.q}</span>
                <span className="faq-chevron shrink-0" aria-hidden="true" style={{ color: "var(--filament-text)" }}>
                  +
                </span>
              </summary>
              <p className="max-w-prose px-4 pb-5 leading-relaxed md:px-6" style={{ color: "var(--ink-muted)" }}>
                {f.a}
              </p>
            </details>
          ))}
        </div>
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd()).replace(/</g, "\\u003c") }} />
      </section>

      {/* 6. Контакты и карта самовывоза */}
      <section className="flex flex-col gap-6" aria-labelledby="contacts">
        <SectionTitle id="contacts" title="Контакты и самовывоз" />
        <div className="grid gap-4 md:grid-cols-[1fr_1.4fr]">
          <div className="card flex flex-col gap-4">
            <dl className="flex flex-col gap-4">
              {/* Пустые контакты не показываем вовсе: «уточняется» на главной выглядит как однодневка. */}
              {contactRows().map((r) => (
                <div key={r.key}>
                  <dt className="t-caption" style={{ color: "var(--ink-muted)" }}>
                    {r.label}
                  </dt>
                  <dd>
                    {r.href ? (
                      <a href={r.href} className="underline underline-offset-2" rel="noopener">
                        {r.text}
                      </a>
                    ) : (
                      r.text
                    )}
                  </dd>
                </div>
              ))}
              {COMPANY.pickupAddress.trim() !== "" && (
                <div>
                  <dt className="t-caption" style={{ color: "var(--ink-muted)" }}>
                    Самовывоз
                  </dt>
                  <dd>
                    {COMPANY.city}, {COMPANY.pickupAddress.trim()}
                  </dd>
                  {COMPANY.hours.trim() !== "" && (
                    <dd className="text-sm" style={{ color: "var(--ink-muted)" }}>
                      {COMPANY.hours.trim()}
                    </dd>
                  )}
                </div>
              )}
            </dl>
            <Link href="/contacts" className="text-sm underline underline-offset-2" style={{ color: "var(--filament-text)" }}>
              Все контакты и реквизиты →
            </Link>
          </div>
          {map ? (
            // Карта грузится лениво и только когда владелец вписал адрес виджета (company.ts → pickupMapUrl).
            <iframe
              src={map}
              title={`Карта: самовывоз ${COMPANY.brand}, ${COMPANY.city}`}
              loading="lazy"
              className="min-h-72 w-full rounded-md border-0"
              style={{ background: "var(--sand)" }}
              allowFullScreen
            />
          ) : (
            <div className="card-sand flex min-h-56 flex-col items-center justify-center gap-2 text-center md:min-h-72" data-testid="map-placeholder">
              <MarkPlaceholder />
              <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
                Карта появится, когда уточним адрес самовывоза. Пока — курьер по Москве или напишите нам.
              </p>
            </div>
          )}
        </div>
      </section>

      {/* 7. Призыв внизу */}
      <section className="card flex flex-col items-start gap-4 p-6 md:p-10" style={{ background: "var(--sand)", borderColor: "transparent" }} aria-labelledby="cta-title">
        <h2 id="cta-title">Готовы? Загрузите модель</h2>
        <p className="max-w-prose" style={{ color: "var(--ink-muted)" }}>
          Расчёт ни к чему не обязывает: цена видна до оформления заказа.
        </p>
        <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
          <Button href="/upload">Загрузить модель</Button>
          <Button href="/catalog" variant="secondary">
            Выбрать из каталога
          </Button>
        </div>
      </section>
    </main>
  );
}
