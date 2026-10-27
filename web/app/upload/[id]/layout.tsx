import type { Metadata } from "next";

/** Страница загруженной модели — личная ссылка клиента, не для поиска (B25). */
export const metadata: Metadata = {
  title: "Ваша модель — ТУЦ",
  robots: { index: false, follow: false },
};

export default function UploadLayout({ children }: { children: React.ReactNode }) {
  return children;
}
