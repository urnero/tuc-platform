import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ТУЦ — 3D-печать на заказ в Москве",
  description: "Загрузите модель, получите цену за минуту, оплатите онлайн.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
