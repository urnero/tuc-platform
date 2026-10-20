import type { Metadata } from "next";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import "./globals.css";

export const metadata: Metadata = {
  title: "ТУЦ — 3D-печать на заказ в Москве",
  description: "Загрузите модель, получите цену за минуту, оплатите онлайн.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className="scroll-smooth">
      {/* flex-колонка, чтобы подвал прижимался к низу даже на коротких страницах */}
      <body className="flex min-h-screen flex-col antialiased">
        <SiteHeader />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
