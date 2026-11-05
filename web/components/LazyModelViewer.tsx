"use client";

/**
 * 3D-просмотр, который не тормозит первую загрузку страницы (UX perf /upload/[id]).
 * Правила — в lib/viewer.ts: на десктопе three.js грузится сам, когда окно видно и браузер
 * свободен; на телефоне — карточка с кнопкой «Показать модель в 3D».
 * Пропсы те же, что у ModelViewer.
 */

import dynamic from "next/dynamic";
import { type ComponentProps, type ReactNode, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui";
import { placeholderHeight, shouldAutoLoad3D } from "@/lib/viewer";

const ModelViewer = dynamic(() => import("@/components/ModelViewer"), {
  ssr: false,
  loading: () => <Box height={420}>Загружаем 3D-просмотр…</Box>,
});

type Props = ComponentProps<typeof ModelViewer>;

function Box({ height, children }: { height: number; children: ReactNode }) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-3 rounded-lg border px-4 text-center text-sm"
      style={{ borderColor: "var(--ink-muted)", height }}
      data-testid="viewer-placeholder"
    >
      {children}
    </div>
  );
}

export default function LazyModelViewer(props: Props) {
  const height = props.height ?? 420;
  // Решаем сразу при первом рендере (на сервере компонент не рисуется — страница ждёт данные
  // загрузки), чтобы заглушка не меняла высоту после первого кадра (CLS).
  const [auto] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    const conn = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    return shouldAutoLoad3D({ width: window.innerWidth, saveData: conn?.saveData });
  });
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Десктоп: ждём, пока окно просмотра появится на экране и браузер освободится.
  useEffect(() => {
    if (!auto || show || !ref.current) return;
    let idle: number | undefined;
    const start = () => {
      const ric = window.requestIdleCallback;
      if (ric) idle = ric(() => setShow(true), { timeout: 2000 });
      else idle = window.setTimeout(() => setShow(true), 200);
    };
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        io.disconnect();
        start();
      }
    });
    io.observe(ref.current);
    return () => {
      io.disconnect();
      if (idle !== undefined) {
        if (window.cancelIdleCallback) window.cancelIdleCallback(idle);
        window.clearTimeout(idle);
      }
    };
  }, [auto, show]);

  if (show) return <ModelViewer {...props} />;

  return (
    <div ref={ref}>
      {!auto ? (
        <Box height={placeholderHeight(false, height)}>
          <span style={{ color: "var(--ink-muted)" }}>3D-просмотр загружается по нажатию — так страница быстрее.</span>
          <Button variant="secondary" size="sm" onClick={() => setShow(true)}>
            Показать модель в 3D
          </Button>
        </Box>
      ) : (
        <Box height={placeholderHeight(true, height)}>Загружаем 3D-просмотр…</Box>
      )}
    </div>
  );
}
