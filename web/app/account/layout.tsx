import type { Metadata } from "next";

/** Кабинет клиента (B32) — личные данные, не для поиска. */
export const metadata: Metadata = {
  title: "Кабинет — BroPrint",
  robots: { index: false, follow: false },
};

export default function AccountLayout({ children }: { children: React.ReactNode }) {
  return children;
}
