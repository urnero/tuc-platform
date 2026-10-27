import type { Metadata } from "next";
import SiteFooter from "@/components/SiteFooter";
import Metrika from "@/components/Metrika";
import SiteHeader from "@/components/SiteHeader";
import { SITE_NAME, siteUrl } from "@/lib/seo";
import "./globals.css";

// metadataBase (B25): относительные canonical / og:url на страницах становятся абсолютными
// адресами сайта из SITE_URL. openGraph здесь — только общее (название сайта, язык);
// заголовок и описание карточки каждая страница берёт свои (Next подставляет их из title).
export const metadata: Metadata = {
  metadataBase: new URL(siteUrl()),
  title: "ТУЦ — 3D-печать на заказ в Москве",
  description: "Загрузите модель, получите цену за минуту, оплатите онлайн.",
  openGraph: { siteName: SITE_NAME, locale: "ru_RU", type: "website" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className="scroll-smooth">
      {/* flex-колонка, чтобы подвал прижимался к низу даже на коротких страницах */}
      <body className="flex min-h-screen flex-col antialiased">
        <Metrika />
        <SiteHeader />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
