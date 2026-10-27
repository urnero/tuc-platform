import type { Metadata, Viewport } from "next";
import "@fontsource/unbounded/700.css";
import "@fontsource-variable/manrope";
import SiteFooter from "@/components/SiteFooter";
import Metrika from "@/components/Metrika";
import SiteHeader from "@/components/SiteHeader";
import { SITE_NAME, siteUrl } from "@/lib/seo";
import { THEME_INIT_SCRIPT } from "@/lib/ui";
import "./globals.css";

// metadataBase (B25): относительные canonical / og:url на страницах становятся абсолютными
// адресами сайта из SITE_URL. openGraph здесь — только общее (название сайта, язык);
// заголовок и описание карточки каждая страница берёт свои (Next подставляет их из title).
// Фавикон — app/icon.svg и app/apple-icon.png из знака (B40), Next подключает их сам.
export const metadata: Metadata = {
  metadataBase: new URL(siteUrl()),
  title: `${SITE_NAME} (БроПринт) — 3D-печать на заказ в Москве`,
  description: "Семейная мастерская 3D-печати. Загрузите модель, получите цену за минуту, оплатите онлайн.",
  openGraph: { siteName: SITE_NAME, locale: "ru_RU", type: "website" },
};

// Цвет адресной строки в мобильных браузерах под тему (surface из docs/DESIGN.md).
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F5F2EC" },
    { media: "(prefers-color-scheme: dark)", color: "#17181A" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: скрипт ниже ставит data-theme до гидрации, React не должен ругаться.
    <html lang="ru" className="scroll-smooth" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
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
