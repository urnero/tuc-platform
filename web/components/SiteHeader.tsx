/**
 * Шапка сайта (B14 → B40): логотип BroPrint, ссылки, переключатель темы и кнопка «Загрузить модель».
 * На телефоне ссылки прячутся в меню-«бургер» (components/MobileMenu.tsx, без JS-состояния на сервере).
 * Подключена в app/layout.tsx — видна на всех страницах.
 */

import Link from "next/link";
import MobileMenu from "@/components/MobileMenu";
import { Button, Logo, ThemeToggle } from "@/components/ui";

export const NAV_LINKS = [
  { href: "/catalog", label: "Каталог" },
  { href: "/editors", label: "Редакторы" },
  { href: "/#how", label: "Как это работает" },
  { href: "/#materials", label: "Материалы" },
  { href: "/contacts", label: "Контакты" },
  { href: "/account", label: "Кабинет" }, // история заказов (B32)
];

export default function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b" style={{ background: "color-mix(in srgb, var(--surface) 92%, transparent)", borderColor: "var(--line)", backdropFilter: "blur(8px)" }}>
      <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3">
        <Link href="/" aria-label="BroPrint — на главную" className="shrink-0">
          <Logo kind="lockup" height={32} />
        </Link>
        <nav className="ml-auto hidden items-center gap-5 text-sm font-semibold lg:flex" style={{ color: "var(--ink-muted)" }} aria-label="Разделы сайта">
          {NAV_LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="hover:text-ink underline-offset-4 hover:underline">
              {l.label}
            </Link>
          ))}
        </nav>
        <ThemeToggle className="ml-auto flex h-10 w-10 items-center justify-center rounded-md hover:bg-sand lg:ml-0" />
        <Button href="/upload" size="sm" className="hidden sm:inline-flex">
          Загрузить модель
        </Button>
        <MobileMenu links={NAV_LINKS} />
      </div>
    </header>
  );
}
