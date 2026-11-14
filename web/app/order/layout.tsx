import type { Metadata } from "next";

/** Страницы заказа (форма и статус по личной ссылке) — не для поиска (B25). */
export const metadata: Metadata = {
  title: "Заказ — BroPrint",
  // Описание нужно и закрытой от поиска странице: его показывают мессенджеры в превью ссылки.
  description: "Оформление и статус заказа 3D-печати в студии BroPrint: состав, оплата, этапы печати.",
  robots: { index: false, follow: false },
};

export default function OrderLayout({ children }: { children: React.ReactNode }) {
  return children;
}
