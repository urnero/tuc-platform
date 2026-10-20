import type { Metadata } from "next";
import SiteFooter from "@/components/SiteFooter";
import "./globals.css";

export const metadata: Metadata = {
  title: "ТУЦ — 3D-печать на заказ в Москве",
  description: "Загрузите модель, получите цену за минуту, оплатите онлайн.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      {/* flex-колонка, чтобы подвал прижимался к низу даже на коротких страницах */}
      <body className="flex min-h-screen flex-col antialiased">
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
