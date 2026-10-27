/**
 * Страница редактора (B21): форма параметров → сборка модели на сервере (OpenSCAD) →
 * 3D-просмотр → «Заказать». Серверный компонент отдаёт схему и метатеги; сама форма,
 * опрос сборки и просмотр — в клиентском EditorWorkbench.
 *
 * SEO (B25): страница рендерится на сервере целиком — заголовок, описание, таблица
 * параметров с диапазонами, правила и шаги заказа есть в HTML до любого JavaScript;
 * канонический адрес и карточка для мессенджеров — через lib/seo.ts; структурированные
 * данные schema.org (хлебные крошки + веб-приложение) — JSON-LD внизу.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import EditorWorkbench from "@/components/EditorWorkbench";
import { type Editor, loadEditor } from "@/lib/editors";
import { checkText, editorJsonLd, metaDescription, pageMetadata, paramDefaultText, paramRangeText } from "@/lib/seo";

type Params = { params: Promise<{ slug: string }> };

const BORDER = { borderColor: "var(--line)" };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const editor = await loadEditor(slug);
  if (!editor) return { title: "Редактор не найден — BroPrint", robots: { index: false } };
  return pageMetadata({
    path: `/editors/${editor.slug}`,
    title: `${editor.title} по вашим размерам — 3D-печать — BroPrint`,
    description: metaDescription(
      editor.text,
      `Задайте размеры «${editor.title}» — модель построится сразу, дальше цена и заказ.`,
    ),
  });
}

/** Таблица «что можно задать» — обычный HTML, его видят поисковики и читалки. */
function ParamsTable({ editor }: { editor: Editor }) {
  return (
    <section className="flex flex-col gap-3" aria-labelledby="params-heading">
      <h2 id="params-heading" className="text-lg font-semibold">
        Что можно задать
      </h2>
      <div className="card overflow-x-auto !p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left" style={{ color: "var(--ink-muted)" }}>
              <th className="px-3 py-2 font-medium">Параметр</th>
              <th className="px-3 py-2 font-medium">Диапазон</th>
              <th className="px-3 py-2 font-medium">По умолчанию</th>
            </tr>
          </thead>
          <tbody>
            {editor.params.map((p) => (
              <tr key={p.name} className="border-t" style={BORDER}>
                <td className="px-3 py-2">
                  {p.label}
                  {p.hint && (
                    <span className="block text-xs" style={{ color: "var(--ink-muted)" }}>
                      {p.hint}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">{paramRangeText(p)}</td>
                <td className="px-3 py-2">{paramDefaultText(p)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editor.checks.length > 0 && (
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
          Ограничения: {editor.checks.map(checkText).join("; ")}. Форма подскажет, если размеры не сходятся.
        </p>
      )}
    </section>
  );
}

const HOW_TO: { title: string; text: string }[] = [
  { title: "Впишите размеры", text: "Превью обновляется само через секунду после правки — покрутите модель в 3D и проверьте со всех сторон." },
  { title: "Нажмите «Заказать»", text: "Готовая модель станет вашей загрузкой: выберите материал, тираж и доставку — цена считается сразу." },
  { title: "Оплатите онлайн", text: "После оплаты заказ уходит в печать, статус — по ссылке: принят → оплачен → печатается → готов." },
];

export default async function EditorPage({ params }: Params) {
  const { slug } = await params;
  const editor = await loadEditor(slug);
  if (!editor) notFound();

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 pb-20 pt-8">
      <nav aria-label="Хлебные крошки" className="text-sm" style={{ color: "var(--filament-text)" }}>
        <Link href="/editors">← Все редакторы</Link>
      </nav>
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold leading-tight">{editor.title}</h1>
        {editor.text && (
          <p className="max-w-prose leading-relaxed" style={{ color: "var(--ink-muted)" }}>
            {editor.text}
          </p>
        )}
      </div>
      <EditorWorkbench editor={editor} />

      <ParamsTable editor={editor} />

      <section className="flex flex-col gap-3" aria-labelledby="howto-heading">
        <h2 id="howto-heading" className="text-lg font-semibold">
          Как заказать печать
        </h2>
        <ol className="grid gap-4 sm:grid-cols-3">
          {HOW_TO.map((step, i) => (
            <li key={step.title} className="card">
              <p className="font-medium">
                {i + 1}. {step.title}
              </p>
              <p className="mt-1 text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                {step.text}
              </p>
            </li>
          ))}
        </ol>
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
          Материал по умолчанию — {editor.material}; при расчёте его можно поменять. Нужна другая деталь? Посмотрите{" "}
          <Link href="/editors" className="underline-offset-2 hover:underline" style={{ color: "var(--filament-text)" }}>
            остальные редакторы
          </Link>
          ,{" "}
          <Link href="/catalog" className="underline-offset-2 hover:underline" style={{ color: "var(--filament-text)" }}>
            каталог готовых моделей
          </Link>{" "}
          или{" "}
          <Link href="/upload" className="underline-offset-2 hover:underline" style={{ color: "var(--filament-text)" }}>
            загрузите свою
          </Link>
          .
        </p>
      </section>

      {/* schema.org для поисковиков; JSON без пользовательского ввода, кроме текстов из editor.yaml владельца */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(editorJsonLd(editor)).replace(/</g, "\\u003c") }}
      />
    </main>
  );
}
