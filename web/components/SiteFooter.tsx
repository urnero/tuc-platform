/**
 * Подвал сайта (B13): ссылки на оферту, политику ПДн, «О студии» и контакты.
 * Подключён в app/layout.tsx — виден на всех страницах.
 */

import Link from "next/link";
import { COMPANY, requisite } from "@/lib/company";

const LINKS = [
  { href: "/about", label: "О студии" },
  { href: "/contacts", label: "Контакты" },
  { href: "/offer", label: "Оферта" },
  { href: "/policy", label: "Политика ПДн" },
];

export default function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="mx-auto mt-auto flex w-full max-w-5xl flex-col gap-2 px-4 py-8 text-sm" style={{ color: "var(--muted)" }}>
      <nav className="flex flex-wrap gap-x-4 gap-y-1">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className="underline-offset-2 hover:underline">
            {l.label}
          </Link>
        ))}
      </nav>
      <p>
        © {year} {COMPANY.brand} · 3D-печать · {COMPANY.city}
        {COMPANY.legalName.trim() !== "" && <> · {requisite("legalName")}</>}
      </p>
    </footer>
  );
}
