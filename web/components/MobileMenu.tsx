"use client";

/**
 * Мобильное меню (B40): кнопка-«бургер» в шапке, по нажатию — список разделов и кнопка
 * «Загрузить модель». Закрывается по клику на ссылку, по Esc и при переходе на другую страницу.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui";

type LinkItem = { href: string; label: string };

export default function MobileMenu({ links }: { links: LinkItem[] }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="lg:hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="mobile-menu"
        aria-label={open ? "Закрыть меню" : "Открыть меню"}
        className="flex h-10 w-10 items-center justify-center rounded-md hover:bg-sand"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          {open ? <path d="M6 6l12 12M18 6 6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
        </svg>
      </button>
      {open && (
        <div id="mobile-menu" className="absolute inset-x-0 top-full border-b shadow-lg" style={{ background: "var(--surface-raised)", borderColor: "var(--line)" }}>
          <nav className="mx-auto flex w-full max-w-6xl flex-col px-4 py-2" aria-label="Разделы сайта">
            {links.map((l) => (
              <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className="border-b py-3 text-base font-semibold" style={{ borderColor: "var(--line)" }}>
                {l.label}
              </Link>
            ))}
            <div className="py-4">
              <Button href="/upload" className="w-full">
                Загрузить модель
              </Button>
            </div>
          </nav>
        </div>
      )}
    </div>
  );
}
