import Link from "next/link";
import { formatPrice } from "@/lib/format";

export default function Home() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-16">
      <p className="text-xs uppercase tracking-widest" style={{ color: "var(--accent)" }}>
        ТУЦ · 3D-печать · Москва
      </p>
      <h1 className="text-3xl font-bold leading-tight">
        Загрузите модель — получите цену за минуту
      </h1>
      <p className="max-w-prose" style={{ color: "var(--muted)" }}>
        Сайт собирается. Загрузка моделей, расчёт и оплата появятся по мере готовности.
        Минимальный заказ от {formatPrice(500)}.
      </p>
      <div className="flex gap-3">
        <Link
          href="/upload"
          className="w-fit rounded-md px-4 py-2 text-sm font-medium"
          style={{ background: "var(--accent)", color: "var(--bg, #fff)" }}
        >
          Загрузить модель
        </Link>
        <a
          href="/api/v1/ping"
          className="w-fit rounded-md border px-4 py-2 text-sm"
          style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
        >
          Проверить API
        </a>
      </div>
    </main>
  );
}
