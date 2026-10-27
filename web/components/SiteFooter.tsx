/**
 * Подвал сайта (B13 → B40): знак и слоган, разделы, документы, контакты из lib/company.ts.
 * Подключён в app/layout.tsx — виден на всех страницах.
 */

import Link from "next/link";
import { Logo } from "@/components/ui";
import { COMPANY, requisite } from "@/lib/company";

const SECTIONS = [
  { href: "/upload", label: "Загрузить модель" },
  { href: "/catalog", label: "Каталог" },
  { href: "/editors", label: "Редакторы" },
  { href: "/account", label: "Кабинет" },
];

const DOCS = [
  { href: "/about", label: "О мастерской" },
  { href: "/contacts", label: "Контакты" },
  { href: "/offer", label: "Оферта" },
  { href: "/policy", label: "Политика ПДн" },
];

export default function SiteFooter() {
  const year = new Date().getFullYear();
  const linkCls = "underline-offset-4 hover:underline";
  return (
    <footer className="mt-auto border-t" style={{ borderColor: "var(--line)", color: "var(--ink-muted)" }}>
      <div className="mx-auto grid w-full max-w-6xl gap-8 px-4 py-10 text-sm sm:grid-cols-[1.4fr_1fr_1fr]">
        <div className="flex flex-col gap-3">
          <Logo kind="mark" height={40} />
          <p className="t-lead max-w-xs" style={{ color: "var(--ink)" }}>
            Воплотим любую идею в жизнь.
          </p>
          <p>Семейная мастерская 3D-печати · {COMPANY.city}</p>
        </div>
        <nav className="flex flex-col gap-2" aria-label="Разделы">
          <span className="t-caption uppercase" style={{ color: "var(--steel)" }}>
            Заказать
          </span>
          {SECTIONS.map((l) => (
            <Link key={l.href} href={l.href} className={linkCls}>
              {l.label}
            </Link>
          ))}
        </nav>
        <nav className="flex flex-col gap-2" aria-label="О нас и документы">
          <span className="t-caption uppercase" style={{ color: "var(--steel)" }}>
            О нас
          </span>
          {DOCS.map((l) => (
            <Link key={l.href} href={l.href} className={linkCls}>
              {l.label}
            </Link>
          ))}
          {COMPANY.telegram.trim() !== "" && (
            <a href={`https://t.me/${COMPANY.telegram}`} className={linkCls} rel="noopener">
              Telegram @{COMPANY.telegram}
            </a>
          )}
          {COMPANY.phone.trim() !== "" && (
            <a href={`tel:${COMPANY.phone.replace(/[^\d+]/g, "")}`} className={linkCls}>
              {COMPANY.phone}
            </a>
          )}
        </nav>
      </div>
      <div className="mx-auto w-full max-w-6xl px-4 pb-8 text-xs">
        © {year} {COMPANY.brand} (БроПринт) · 3D-печать · {COMPANY.city}
        {COMPANY.legalName.trim() !== "" && <> · {requisite("legalName")}</>}
      </div>
    </footer>
  );
}
