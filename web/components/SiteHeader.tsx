/**
 * Шапка сайта (B14): название — ссылка на главную, пара ссылок и кнопка «Загрузить модель».
 * Подключена в app/layout.tsx — видна на всех страницах. Без состояния, серверный компонент.
 */

import Link from "next/link";
import { COMPANY } from "@/lib/company";

const LINKS = [
  { href: "/catalog", label: "Каталог" },
  { href: "/editors", label: "Редакторы" },
  { href: "/#how", label: "Как это работает" },
  { href: "/#materials", label: "Материалы" },
  { href: "/contacts", label: "Контакты" },
  { href: "/account", label: "Кабинет" }, // история заказов (B32)
];

export default function SiteHeader() {
  return (
    <header className="mx-auto flex w-full max-w-5xl items-center gap-4 px-4 py-4 text-sm">
      <Link href="/" className="text-lg font-bold tracking-tight" aria-label="На главную">
        {COMPANY.brand}
        <span className="ml-2 hidden text-xs font-normal uppercase tracking-widest sm:inline" style={{ color: "var(--muted)" }}>
          3D-печать · {COMPANY.city}
        </span>
      </Link>
      <nav className="ml-auto hidden gap-4 md:flex" style={{ color: "var(--muted)" }}>
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className="underline-offset-2 hover:underline">
            {l.label}
          </Link>
        ))}
      </nav>
      <Link
        href="/upload"
        className="ml-auto rounded-md px-3 py-1.5 font-medium md:ml-0"
        style={{ background: "var(--accent)", color: "var(--bg, #fff)" }}
      >
        Загрузить модель
      </Link>
    </header>
  );
}
