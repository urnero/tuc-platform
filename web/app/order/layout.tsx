import type { Metadata } from "next";

/** Страницы заказа (форма и статус по личной ссылке) — не для поиска (B25). */
export const metadata: Metadata = {
  title: "Заказ — BroPrint",
  robots: { index: false, follow: false },
};

export default function OrderLayout({ children }: { children: React.ReactNode }) {
  return children;
}
